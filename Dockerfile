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

# 런타임 의존성만(onnxruntime + tokenizer + fastapi). torch/optimum 불포함 → 경량.
RUN pip install --upgrade pip && pip install .

# 모델 아티팩트(model_quantized.onnx + tokenizer ~560MB)는 **이미지에 동봉하지 않는다**.
# 아티팩트 공급 방식 미정(빌드 동봉 vs 사전생성 checksum vs 볼륨/initContainer) → 운영에선 RERANKER_ONNX_DIR에 마운트.
# (README "모델 아티팩트" 참조)

USER onramp
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3).read()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
