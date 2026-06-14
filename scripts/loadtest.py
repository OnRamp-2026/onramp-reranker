"""임시 부하 측정 — /rerank 동시·반복 호출 latency (#72 1단계 검증용).

메모리는 kubectl exec 로 cgroup(memory.stat anon / memory.peak)을 별도 확인.
사용: python scripts/loadtest.py [URL] [CONCURRENCY] [ROUNDS]
예:   python scripts/loadtest.py http://127.0.0.1:18080/rerank 4 20
"""

from __future__ import annotations

import asyncio
import statistics
import sys
import time

import httpx

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18080/rerank"
CONCURRENCY = int(sys.argv[2]) if len(sys.argv) > 2 else 4
ROUNDS = int(sys.argv[3]) if len(sys.argv) > 3 else 20

QUERY = "Apache Directory 지시문에서 디렉토리 경로 처리"
PASSAGES = [
    "mod_authnz_ldap는 LDAP 디렉토리로 인증/인가를 제공한다.",
    "<Directory> 섹션은 지정 경로에 적용되는 지시문을 묶는다.",
    "Datadog DD_ENV/DD_SERVICE/DD_VERSION 태그를 설정한다.",
    "kubectl describe pod로 컨테이너 상태를 확인한다.",
    "H2MaxHeaderBlockLen 설정의 기본값.",
] * 4  # ~20 (운영 top_k 모사)


async def _one(client: httpx.AsyncClient) -> float:
    t = time.time()
    r = await client.post(URL, json={"query": QUERY, "passages": PASSAGES})
    r.raise_for_status()
    assert len(r.json()["scores"]) == len(PASSAGES)
    return time.time() - t


async def main() -> None:
    latencies: list[float] = []
    async with httpx.AsyncClient(timeout=180) as client:
        await _one(client)  # warmup
        for _ in range(ROUNDS):
            latencies += await asyncio.gather(*[_one(client) for _ in range(CONCURRENCY)])
    latencies.sort()
    p95 = latencies[min(int(len(latencies) * 0.95), len(latencies) - 1)]
    print(
        f"n={len(latencies)} concurrency={CONCURRENCY} "
        f"p50={statistics.median(latencies):.2f}s p95={p95:.2f}s max={latencies[-1]:.2f}s",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
