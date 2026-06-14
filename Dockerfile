# ── builder: ONNX 변환·int8 양자화 (torch/optimum 사용, 최종 이미지엔 미포함) ──
FROM python:3.11-slim AS builder

ARG RERANKER_MODEL=BAAI/bge-reranker-v2-m3
# 운영 노드 CPU 명령셋. avx512_vnni 미지원 노드 → avx2(기본) 또는 avx512.
ARG RERANKER_ARCH=avx2

ENV PIP_NO_CACHE_DIR=1
WORKDIR /build

# CPU torch(경량) + optimum/onnx 변환 의존성. (builder 스테이지라 최종 이미지 크기 무관)
RUN pip install --upgrade pip \
    && pip install --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install "optimum[onnxruntime]>=1.20" "onnx>=1.17" "transformers>=4.41,<5"

COPY scripts/build_onnx.py ./build_onnx.py
# 빌드 시 HF에서 base 모델(~2.2GB) 다운로드 → 변환·양자화 → /models/bge-reranker-onnx-int8 (model_quantized.onnx + tokenizer)
RUN python build_onnx.py --out /models/bge-reranker-onnx-int8 --arch "${RERANKER_ARCH}" --model "${RERANKER_MODEL}"

# ── runtime: torch-free 경량 + 굽힌 모델 동봉 ──
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    RERANKER_ONNX_DIR=/models/bge-reranker-onnx-int8 \
    RERANKER_ONNX_FILE=model_quantized.onnx

WORKDIR /app

RUN addgroup --system onramp \
    && adduser --system --ingroup onramp --home /app onramp

COPY --chown=onramp:onramp pyproject.toml ./
COPY --chown=onramp:onramp app ./app

# 런타임 의존성만(onnxruntime + tokenizer + fastapi) — torch/optimum 불포함 → 경량.
RUN pip install --upgrade pip && pip install .

# builder가 구운 int8 모델·tokenizer 동봉 (런타임 다운로드·egress 불필요).
COPY --from=builder --chown=onramp:onramp /models/bge-reranker-onnx-int8 /models/bge-reranker-onnx-int8

USER onramp
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3).read()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
