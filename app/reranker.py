"""ONNX(int8) Cross-Encoder 리랭커 — CPU·torch-free.

onramp-api의 OnnxCrossEncoderReranker와 **동일한 점수 계약**(sigmoid [0,1])을 유지한다.
tokenizer는 모델 디렉터리에서 `local_files_only=True`로 오프라인 로드(런타임 HF 네트워크·writable cache 불필요).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings


class OnnxReranker:
    """model_quantized.onnx + 로컬 tokenizer로 (query, passages) → 점수[0,1]."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._session: Any = None  # onnxruntime.InferenceSession
        self._tokenizer: Any = None
        self._input_names: set[str] = set()
        self._lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._session is not None

    def load(self) -> None:
        """모델·tokenizer 로드. 파일 없으면 명확한 오류로 실패(fail-fast)."""
        if self._session is not None:
            return
        with self._lock:
            if self._session is not None:
                return
            model_dir = Path(self.settings.reranker_onnx_dir)
            model_path = model_dir / self.settings.reranker_onnx_file
            if not model_path.is_file():
                raise RuntimeError(f"ONNX 모델 파일 없음: {model_path}")
            if not (model_dir / "tokenizer.json").is_file():
                raise RuntimeError(f"tokenizer 파일 없음: {model_dir}/tokenizer.json (모델 디렉터리에 동봉 필요)")

            import onnxruntime as ort
            from transformers import AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
            opts = ort.SessionOptions()
            if self.settings.ort_intra_op_threads > 0:
                opts.intra_op_num_threads = self.settings.ort_intra_op_threads
            # 이미지가 onnxruntime-gpu(GPU)면 CUDA 우선, CPU 이미지면 CPU — 단일 코드로 양쪽 지원(#73).
            available = ort.get_available_providers()
            providers = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in available] or [
                "CPUExecutionProvider"
            ]
            self._session = ort.InferenceSession(str(model_path), sess_options=opts, providers=providers)
            self._input_names = {i.name for i in self._session.get_inputs()}

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        """passages 각각에 대한 관련도 점수[0,1]을 **입력 순서대로** 반환."""
        if not passages:
            return []
        if self._session is None:
            self.load()
        import numpy as np

        # passage를 batch_size개씩 나눠 추론 — peak 메모리를 입력 크기와 무관하게 상한(#72 OOM 방지).
        # 분할해도 각 쌍 점수는 독립이라 일괄 추론과 결과 동일.
        bs = max(1, self.settings.batch_size)
        scores: list[float] = []
        for start in range(0, len(passages), bs):
            chunk = passages[start : start + bs]
            features = self._tokenizer(
                [query] * len(chunk),
                chunk,
                padding=True,
                truncation=True,
                max_length=self.settings.max_length,
                return_tensors="np",
            )
            inputs = {k: v for k, v in features.items() if k in self._input_names}
            logits = self._session.run(None, inputs)[0]
            scores.extend((1.0 / (1.0 + np.exp(-logits))).reshape(-1).astype(float).tolist())
        return scores


_reranker: OnnxReranker | None = None
_reranker_lock = threading.Lock()


def get_reranker(settings: Settings | None = None) -> OnnxReranker:
    global _reranker
    with _reranker_lock:
        if _reranker is None:
            _reranker = OnnxReranker(settings)
        return _reranker
