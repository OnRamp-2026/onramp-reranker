"""FastAPI 리랭커 서비스.

- 기동 시 모델 preload → 성공 전 readiness 실패(트래픽 차단). 실패 시 fail-fast 로그.
- `POST /rerank {query, passages[]} → {scores[]}` — onramp-api의 RemoteReranker가 호출.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI, Response, status

from app.config import get_settings
from app.models import RerankRequest, RerankResponse
from app.reranker import get_reranker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("Starting %s %s — preloading ONNX reranker...", settings.app_name, settings.app_version)
    # 모델 로드를 startup에서 수행 → readiness가 로드 완료를 반영. 실패하면 기동 자체가 실패(fail-fast).
    get_reranker(settings).load()
    logger.info("ONNX reranker loaded (dir=%s)", settings.reranker_onnx_dir)
    yield


app = FastAPI(title="OnRamp Reranker", version=get_settings().app_version, lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    """Liveness — 프로세스 생존."""
    return {"status": "ok"}


@app.get("/health/ready")
async def ready(response: Response) -> dict:
    """Readiness — 모델 로드 완료 시에만 ok."""
    if get_reranker().is_loaded:
        return {"status": "ok"}
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "loading"}


@app.post("/rerank", response_model=RerankResponse)
async def rerank(req: RerankRequest) -> RerankResponse:
    """query에 대한 passages 관련도 점수[0,1]을 입력 순서대로 반환."""
    # CPU 동기 추론 → 스레드로 오프로드(이벤트 루프 비차단).
    scores = await anyio.to_thread.run_sync(get_reranker().rerank, req.query, req.passages)
    return RerankResponse(scores=scores)
