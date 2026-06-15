"""리랭커 서비스 설정 (env 주입)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "OnRamp Reranker"
    app_version: str = "0.1.0"

    # ONNX 산출물(model_quantized.onnx + tokenizer 파일)이 있는 디렉터리.
    # 이미지에 동봉하거나 볼륨으로 마운트한다. tokenizer는 이 디렉터리에서 오프라인 로드.
    reranker_onnx_dir: str = "/models/bge-reranker-onnx-int8"
    reranker_onnx_file: str = "model_quantized.onnx"

    # 토큰화 상한 (query+passage 쌍).
    max_length: int = 512

    # 추론 sub-batch 크기. passage가 많아도 batch_size개씩 나눠 추론해 peak 메모리를
    # 입력 크기와 무관하게 상한(#72: 실부하 20개 일괄 추론 시 OOM → 분할). 점수 결과는 동일.
    batch_size: int = 8

    # ONNX Runtime intra-op 스레드 (0=기본). CPU 파드에서 과도한 스레드 메모리 방지용으로 조절 가능.
    ort_intra_op_threads: int = 0

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "case_sensitive": False}


@lru_cache
def get_settings() -> Settings:
    return Settings()
