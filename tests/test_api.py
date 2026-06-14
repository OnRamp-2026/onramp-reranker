"""API 엔드포인트 — 실제 모델 없이 stub 리랭커로 검증."""

from fastapi.testclient import TestClient

from app import main


class _StubReranker:
    is_loaded = True

    def load(self) -> None:  # lifespan preload no-op
        pass

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        return [0.9] * len(passages)


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(main, "get_reranker", lambda *a, **k: _StubReranker())
    return TestClient(main.app)


def test_rerank_endpoint(monkeypatch):
    with _client(monkeypatch) as client:
        r = client.post("/rerank", json={"query": "q", "passages": ["a", "b"]})
        assert r.status_code == 200
        assert r.json() == {"scores": [0.9, 0.9]}


def test_health_and_ready(monkeypatch):
    with _client(monkeypatch) as client:
        assert client.get("/health").json()["status"] == "ok"
        ready = client.get("/health/ready")
        assert ready.status_code == 200 and ready.json()["status"] == "ok"


def test_rerank_rejects_empty_query(monkeypatch):
    with _client(monkeypatch) as client:
        assert client.post("/rerank", json={"query": "", "passages": ["a"]}).status_code == 422
