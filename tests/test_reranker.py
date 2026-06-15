"""OnnxReranker 추론 로직 — 실제 모델 없이 stub session/tokenizer로 점수 계약 검증."""

import numpy as np

from app.reranker import OnnxReranker


class _StubTokenizer:
    def __call__(self, queries, passages, **kw):
        n = len(passages)
        return {
            "input_ids": np.ones((n, 4), dtype=np.int64),
            "attention_mask": np.ones((n, 4), dtype=np.int64),
        }


class _Inp:
    def __init__(self, name: str) -> None:
        self.name = name


class _StubSession:
    def __init__(self, logits):
        self._logits = logits

    def get_inputs(self):
        return [_Inp("input_ids"), _Inp("attention_mask")]

    def run(self, _outputs, inputs):
        return [np.array(self._logits, dtype=np.float32).reshape(-1, 1)]


def _loaded(logits) -> OnnxReranker:
    r = OnnxReranker()
    r._tokenizer = _StubTokenizer()
    r._session = _StubSession(logits)
    r._input_names = {"input_ids", "attention_mask"}
    return r


def test_rerank_returns_sigmoid_scores_in_input_order():
    r = _loaded([2.0, -2.0, 0.0])
    scores = r.rerank("q", ["a", "b", "c"])
    assert len(scores) == 3
    assert scores[0] > 0.8  # sigmoid(2) ~ 0.88
    assert scores[1] < 0.2  # sigmoid(-2) ~ 0.12
    assert abs(scores[2] - 0.5) < 1e-6  # sigmoid(0) = 0.5
    assert scores[0] > scores[2] > scores[1]  # 순서 보존


def test_rerank_empty_passages():
    assert _loaded([]).rerank("q", []) == []


def test_is_loaded_flag():
    assert _loaded([1.0]).is_loaded is True
    assert OnnxReranker().is_loaded is False


class _ChunkSession:
    """입력 배치 행 수만큼 미리 정한 logits를 순서대로 소비 — sub-batch 분할 검증용."""

    def __init__(self, logits):
        self._logits = list(logits)
        self._pos = 0
        self.run_calls = 0

    def get_inputs(self):
        return [_Inp("input_ids"), _Inp("attention_mask")]

    def run(self, _outputs, inputs):
        self.run_calls += 1
        n = inputs["input_ids"].shape[0]
        out = self._logits[self._pos : self._pos + n]
        self._pos += n
        return [np.array(out, dtype=np.float32).reshape(-1, 1)]


def test_rerank_subbatch_matches_full_and_preserves_order():
    import math

    from app.config import Settings

    logits = [2.0, -2.0, 0.0, 1.5, -1.0]
    r = OnnxReranker(Settings(batch_size=2))  # 5개를 2,2,1 로 분할
    r._tokenizer = _StubTokenizer()
    sess = _ChunkSession(logits)
    r._session = sess
    r._input_names = {"input_ids", "attention_mask"}

    scores = r.rerank("q", ["a", "b", "c", "d", "e"])

    assert sess.run_calls == 3  # 분할 추론 확인 (2+2+1)
    expected = [1.0 / (1.0 + math.exp(-x)) for x in logits]
    assert len(scores) == 5
    for s, e in zip(scores, expected, strict=True):
        assert abs(s - e) < 1e-6  # 분할해도 일괄과 동일 점수·순서
