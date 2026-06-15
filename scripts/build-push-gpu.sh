#!/bin/bash
# GPU 리랭커 이미지 1회 수동 빌드·push (L40S 검증용, Jenkins 자동화 전 단계).
#
# 사용:
#   GHCR_USER=<github-id> GHCR_PAT=<write:packages PAT> ./scripts/build-push-gpu.sh [tag]
#   (tag 생략 시 gpu-v1)
#
# 준비물:
#   - Docker Desktop 실행(메모리 넉넉히 — amd64 에뮬레이션 빌드)
#   - GitHub PAT (scope: write:packages), onramp-2026 org 패키지 push 권한
#   - torch/optimum 설치 가능한 파이썬 (fp32 모델 생성용)
set -euo pipefail

TAG="${1:-gpu-v1}"
IMAGE="ghcr.io/onramp-2026/onramp-reranker:${TAG}"
MODEL_DIR="models/bge-reranker-onnx-fp32"

cd "$(dirname "$0")/.."

# 1) fp32 ONNX 모델 (없으면 생성 — HF에서 bge-reranker-v2-m3 받아 export, ~2.2GB)
# 호스트 파이썬/venv에 의존하지 않게 python:3.11 컨테이너에서 생성(torch+optimum 격리, 좋은 wheel).
# 컨테이너는 호스트 아키텍처(맥=arm64)로 돌아도 됨 — ONNX 산출물은 플랫폼 독립이라 amd64 이미지에 그대로 사용.
if [ ! -f "${MODEL_DIR}/model.onnx" ]; then
  echo "== [1/3] fp32 모델 생성 (python:3.11 컨테이너에서) =="
  docker run --rm -v "$PWD:/work" -w /work python:3.11-slim bash -c \
    "pip install --no-cache-dir '.[build]' && python scripts/build_onnx.py --precision fp32 --out '${MODEL_DIR}'"
else
  echo "== [1/3] fp32 모델 이미 있음: ${MODEL_DIR}/model.onnx (재생성 생략) =="
fi

# 2) amd64 이미지 빌드 (단일 Dockerfile.gpu — sshd+uvicorn+모델). Mac이면 에뮬레이션이라 느림.
echo "== [2/3] 이미지 빌드: ${IMAGE} (linux/amd64) =="
docker build --platform linux/amd64 -f Dockerfile.gpu -t "${IMAGE}" .

# 3) GHCR 로그인 + push
echo "== [3/3] GHCR push =="
echo "${GHCR_PAT:?GHCR_PAT 환경변수 필요(write:packages PAT)}" \
  | docker login ghcr.io -u "${GHCR_USER:?GHCR_USER 환경변수 필요(github id)}" --password-stdin
docker push "${IMAGE}"

echo
echo "== 완료: ${IMAGE} =="
echo "다음:"
echo "  1) GitHub → onramp-2026/packages → onramp-reranker → Package settings → visibility=Public"
echo "  2) VESSL Custom Image URI 에 ${IMAGE} 입력"
echo "  3) Port: HTTP 8080 + TCP 22, SSH key Generate"
echo "  4) (CMD override 대비) Init script: cd /app && nohup uvicorn app.main:app --host 0.0.0.0 --port 8080 > /tmp/reranker.log 2>&1 &"
