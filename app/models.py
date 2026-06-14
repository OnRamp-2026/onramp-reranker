"""요청/응답 스키마."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RerankRequest(BaseModel):
    query: str = Field(..., min_length=1)
    passages: list[str] = Field(default_factory=list, description="후보 문서 텍스트(순서 보존)")


class RerankResponse(BaseModel):
    # passages 입력 순서와 동일한 점수[0,1]. 호출측(onramp-api)이 payload 재매핑·정렬.
    scores: list[float]
