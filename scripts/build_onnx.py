"""bge-reranker-v2-m3 → ONNX(int8) 변환·양자화. 빌드 동봉용(멀티스테이지 builder에서 실행).

동일 모델을 ONNX 변환 후 동적 int8 양자화한다(다국어 보존 — 가중치 교체 아님).
산출물: <out>/model_quantized.onnx + tokenizer 파일. 런타임은 RERANKER_ONNX_DIR=<out> 로 사용.

의존성: pip install ".[build]"  (optimum + onnx + torch)
실행:   python scripts/build_onnx.py --out /models/bge-reranker-onnx-int8 --arch avx2
        # 운영 노드 CPU에 맞춰 --arch 선택. avx512_vnni 미지원 노드 → avx2(또는 avx512).
"""

from __future__ import annotations

import argparse

DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"


def main() -> None:
    p = argparse.ArgumentParser(description="bge-reranker ONNX int8 변환(빌드 동봉)")
    p.add_argument("--out", default="models/bge-reranker-onnx-int8", help="int8 산출 디렉토리")
    p.add_argument("--fp32-dir", default="models/bge-reranker-onnx-fp32", help="중간 fp32 export 디렉토리")
    p.add_argument(
        "--arch",
        default="avx2",
        choices=["arm64", "avx2", "avx512", "avx512_vnni"],
        help="양자화 타깃 명령셋 (운영 노드 CPU 지원 범위로. avx512_vnni 미지원 노드 → avx2/avx512)",
    )
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"모델명 (기본 {DEFAULT_MODEL})")
    p.add_argument(
        "--precision",
        default="int8",
        choices=["int8", "fp32"],
        help="int8: CPU용 동적 양자화(model_quantized.onnx) | fp32: GPU(VESSL)용, 양자화 생략(model.onnx)",
    )
    args = p.parse_args()

    from optimum.onnxruntime import ORTModelForSequenceClassification, ORTQuantizer
    from optimum.onnxruntime.configuration import AutoQuantizationConfig
    from transformers import AutoTokenizer

    if args.precision == "fp32":
        # GPU(CUDAExecutionProvider)는 fp32 ONNX를 그대로 사용 — int8(QDQ)은 CPU 전용이라 부적합.
        print(f"[1/2] {args.model} → ONNX fp32 export ({args.out}) — GPU용, 양자화 생략", flush=True)
        ort = ORTModelForSequenceClassification.from_pretrained(args.model, export=True)
        ort.save_pretrained(args.out)
        AutoTokenizer.from_pretrained(args.model).save_pretrained(args.out)
        print(f"[2/2] 완료 → {args.out} (model.onnx + tokenizer). 런타임: RERANKER_ONNX_FILE=model.onnx", flush=True)
        return

    print(f"[1/3] {args.model} → ONNX fp32 export ({args.fp32_dir})", flush=True)
    ort = ORTModelForSequenceClassification.from_pretrained(args.model, export=True, provider="CPUExecutionProvider")
    ort.save_pretrained(args.fp32_dir)

    print(f"[2/3] int8 동적 양자화 (arch={args.arch}) → {args.out}", flush=True)
    qcfg = getattr(AutoQuantizationConfig, args.arch)(is_static=False, per_channel=False)
    ORTQuantizer.from_pretrained(args.fp32_dir).quantize(save_dir=args.out, quantization_config=qcfg)
    # 토크나이저는 양자화 성공 후 동봉(실패 시 토크나이저만 있는 불완전 산출물 방지)
    AutoTokenizer.from_pretrained(args.model).save_pretrained(args.out)

    print(f"[3/3] 완료 → {args.out} (model_quantized.onnx + tokenizer)", flush=True)


if __name__ == "__main__":
    main()
