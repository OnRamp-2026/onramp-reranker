#!/usr/bin/env bash
# ⚠️ 임시 검증 전용 — 운영 배포 아님 (#72 1단계).
#   레지스트리 push 없이, onramp-api 운영 이미지를 base로 reranker 코드/모델/onnxruntime를 주입해
#   실제 amd64 노드에서 띄우고 /rerank·메모리를 확인한다(저번 onnx 카나리와 동일 방식).
#   USE_TORCH=0 으로 torch 미적재(경량 이미지 메모리 모사).
set -euo pipefail

# macOS kubectl 1.30+ websocket cp/exec 버그("write: result too large") 회피 → SPDY 사용.
export KUBECTL_REMOTE_COMMAND_WEBSOCKETS=false

ns="${NAMESPACE:-onramp}"
pod="${POD_NAME:-onramp-reranker-canary}"
model_dir="${1:?usage: $0 /absolute/path/to/bge-reranker-onnx-int8}"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -f "${model_dir}/model_quantized.onnx" || ! -f "${model_dir}/tokenizer.json" ]]; then
  echo "invalid model directory: ${model_dir}" >&2
  exit 1
fi

kubectl -n "${ns}" delete pod "${pod}" --ignore-not-found=true
kubectl apply -f "${repo}/deploy/reranker-inject-pod.yaml"
kubectl -n "${ns}" wait --for=condition=Ready "pod/${pod}" --timeout=180s

kubectl -n "${ns}" cp "${model_dir}/." "${pod}:/tmp/onnx-model"
kubectl -n "${ns}" cp "${repo}/app" "${pod}:/tmp/reranker/app"

# onnxruntime만 추가(base 이미지에 fastapi/uvicorn/transformers/numpy 존재).
kubectl -n "${ns}" exec "${pod}" -- \
  python -m pip install --disable-pip-version-check --target /tmp/pydeps "onnxruntime>=1.20,<2"

kubectl -n "${ns}" exec "${pod}" -- sh -c \
  'cd /tmp/reranker && PYTHONPATH=/tmp/pydeps USE_TORCH=0 USE_TF=0 USE_FLAX=0 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 RERANKER_ONNX_DIR=/tmp/onnx-model RERANKER_ONNX_FILE=model_quantized.onnx nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 >/tmp/reranker.log 2>&1 &'

for _ in $(seq 1 90); do
  if kubectl -n "${ns}" exec "${pod}" -- grep -q "Uvicorn running on http://0.0.0.0:8080" /tmp/reranker.log 2>/dev/null; then
    kubectl -n "${ns}" exec "${pod}" -- tail -25 /tmp/reranker.log
    kubectl -n "${ns}" exec "${pod}" -- sh -c \
      'grep -E "^anon |^file " /sys/fs/cgroup/memory.stat; echo current=$(cat /sys/fs/cgroup/memory.current) peak=$(cat /sys/fs/cgroup/memory.peak) max=$(cat /sys/fs/cgroup/memory.max)'
    echo
    echo "Ready. 별도 터미널: kubectl -n ${ns} port-forward pod/${pod} 18080:8080"
    exit 0
  fi
  sleep 2
done

kubectl -n "${ns}" exec "${pod}" -- cat /tmp/reranker.log || true
echo "reranker did not become ready within 180s" >&2
exit 1
