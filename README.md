# onramp-reranker

OnRamp Cross-Encoder 리랭커 서비스 — **ONNX int8 · CPU · torch-free**. `onramp-api`가 HTTP로 호출한다.

## 왜 별도 서비스인가
`bge-reranker-v2-m3`(ONNX int8 ~543MB)를 `onramp-api` 파드에 in-process로 얹으면 현 노드(파드당 ~2.2GB)에서 **요청 처리 중 OOMKilled**(실측). 리랭커만 별도 파드로 분리해 메모리를 떼어낸다.
- 배경·증거: `onramp-api` 레포 `docs/Jihong/fixes/72_reranker_sizing_decision.md` (와 `72_prod_e2e_reranker_bringup.md`)
- 리랭커 품질 기여(측정): dense 대비 **MRR +24% · NDCG +18%** (골든 81문항) → 빼기엔 아까워 분리 선택.

## API
```
POST /rerank   {"query": "...", "passages": ["doc1", "doc2", ...]}
            →  {"scores": [0.83, 0.12, ...]}   # passages 입력 순서대로 [0,1]
GET  /health         # liveness
GET  /health/ready   # readiness — 모델 로드 완료 시에만 200
```
점수는 sigmoid [0,1]로 `onramp-api`의 torch/ONNX 백엔드와 **동일 계약**. 호출측이 점수로 payload 재매핑·정렬한다.

## 로컬 실행
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
# 모델 디렉터리 지정(아래 "모델 아티팩트")
RERANKER_ONNX_DIR=/path/to/bge-reranker-onnx-int8 uvicorn app.main:app --port 8080
```
테스트(모델 불필요 — stub):
```bash
pytest -q
```

## 모델 아티팩트 (~560MB, git 미포함)
`model_quantized.onnx` + tokenizer 파일이 든 디렉터리가 필요하다. **이미지에 동봉하지 않으며**(`.gitignore`), 공급 방식은 **미정(팀 결정)**:
- (A) 빌드 시 생성(ONNX 변환·int8 양자화) — `pip install ".[build]"` 후 변환 스크립트
- (B) 사전 생성 아티팩트를 checksum 고정해 이미지/스토리지에서 COPY
- (C) PVC/initContainer로 런타임 마운트

생성(예, onramp-api의 빌드 스크립트 참고, 운영 CPU에 맞는 arch):
```bash
# avx512_vnni 미지원 노드 → avx2 또는 avx512
python build_reranker_onnx.py --out models/bge-reranker-onnx-int8 --arch avx2
```
런타임은 `RERANKER_ONNX_DIR`이 가리키는 디렉터리에서 tokenizer를 **오프라인**(`local_files_only`)으로 로드한다(HF 네트워크·writable cache 불필요).

## 환경변수
| 변수 | 기본 | 설명 |
|---|---|---|
| `RERANKER_ONNX_DIR` | `/models/bge-reranker-onnx-int8` | 모델·tokenizer 디렉터리 |
| `RERANKER_ONNX_FILE` | `model_quantized.onnx` | ONNX 파일명 |
| `MAX_LENGTH` | `512` | 토큰화 상한 |
| `ORT_INTRA_OP_THREADS` | `0` | ONNX Runtime intra-op 스레드(0=기본) |

## 배포 (예정 — 인프라)
- `Deployment` + `Service`(ClusterIP) → `onramp-api`에서 `RERANKER_BACKEND=remote RERANKER_SERVICE_URL=http://onramp-reranker:8080`.
- readiness probe: `GET /health/ready`(모델 로드 후 트래픽). resources: **메모리는 실측 후 산정**(리랭커 단독 ~1.15GB 참고, 동시성·반복 미검증 → canary로 확정).
- ⚠️ 메모리·동시성은 배포 전 별도 검증 필요(단일 요청 통과로 확정 금지).

## 비범위
- rerank latency(CPU ~5s/요청)는 분리로 줄지 않음 — 별도 최적화(onramp-api #73 경계).
