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

## 모델 아티팩트 — **빌드 동봉(build-time bake)**
모델(`model_quantized.onnx` + tokenizer, ~560MB)은 **멀티스테이지 Docker 빌드에서 생성해 이미지에 굽는다**(`scripts/build_onnx.py`). git에는 모델을 커밋하지 않는다(`.gitignore`).

```bash
# 운영 노드 CPU에 맞춰 arch (avx512_vnni 미지원 → avx2 기본)
docker build --build-arg RERANKER_ARCH=avx2 -t onramp-reranker:dev .
```
- **builder 스테이지**: torch+optimum로 HF에서 base 모델 다운로드 → ONNX 변환 → int8 양자화. (최종 이미지엔 미포함)
- **runtime 스테이지**: torch-free 경량 + builder가 구운 모델만 COPY.
- ⚠️ **빌드 시점 HF egress + 시간 필요**(base 모델 ~2.2GB 다운로드). 모델 무변경 재빌드 시 BuildKit 캐시 권장.
- 런타임은 tokenizer를 이미지 내 디렉터리에서 **오프라인**(`local_files_only`) 로드 → 런타임 HF 네트워크·writable cache 불필요.

### 방식 2: 사전 생성 모델 COPY (`Dockerfile.prebuilt`) — 에뮬레이션·저메모리 환경 권장
빌드 동봉(방식 1)은 builder가 fp32 모델을 메모리에 올려 양자화하므로 **arm맥의 QEMU 에뮬레이션·낮은 Docker 메모리에선 OOM(Killed)** 날 수 있고, **빌드 시 HF 접근**도 필요하다. 이미 만든 모델이 있으면 그걸 그대로 굽는다(양자화·HF 다운로드 없음):
```bash
# 사전 생성 모델을 빌드 컨텍스트로 (models/ 는 .gitignore)
cp -r /path/to/bge-reranker-onnx-int8-avx2/.  models/bge-reranker-onnx-int8/
docker buildx build --platform linux/amd64 -f Dockerfile.prebuilt -t onramp-reranker:dev --load .
```
→ runtime 의존성 설치 + 모델 COPY만이라 **빠르고 OOM 없음**. (방식 1 build-bake는 메모리·HF 충분한 **CI(native amd64)** 에서.)

> 모델을 새로 만들려면: `pip install ".[build]" && python scripts/build_onnx.py --out models/bge-reranker-onnx-int8 --arch avx2`

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
