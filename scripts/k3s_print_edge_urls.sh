#!/usr/bin/env bash
set -euo pipefail

# Print LOCAL_*_URL exports for edge-agent by reading k3s service endpoints.
# Supports ClusterIP or NodePort mode.

KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
NAMESPACE="${NAMESPACE:-default}"
MODE="${MODE:-clusterip}"   # clusterip | nodeport
NODE_IP="${NODE_IP:-}"

EST_SVC="${EST_SVC:-threshold-service}"
DET_SVC="${DET_SVC:-svc-detect}"
FINE_SVC="${FINE_SVC:-suc-fine-detect}"

EST_PATH="${EST_PATH:-/ingest}"
DET_PATH="${DET_PATH:-/detect/eval}"
FINE_PATH="${FINE_PATH:-/fine/eval}"

# For k3s, kubectl often fails with localhost:8080 when kubeconfig is not exported.
if [[ -z "${KUBECONFIG:-}" && -f /etc/rancher/k3s/k3s.yaml ]]; then
  export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
fi

kubectl_ok() {
  "$KUBECTL_BIN" version --request-timeout=3s >/dev/null 2>&1
}

if ! kubectl_ok; then
  if command -v k3s >/dev/null 2>&1; then
    KUBECTL_BIN="k3s kubectl"
  fi
fi

if ! $KUBECTL_BIN version --request-timeout=3s >/dev/null 2>&1; then
  echo "ERROR: cannot connect to Kubernetes API." >&2
  echo "Try one of these on the node:" >&2
  echo "  export KUBECONFIG=/etc/rancher/k3s/k3s.yaml" >&2
  echo "  k3s kubectl get svc -n ${NAMESPACE}" >&2
  exit 1
fi

get_svc_field() {
  local svc="$1" jsonpath="$2"
  $KUBECTL_BIN -n "$NAMESPACE" get svc "$svc" -o "jsonpath=${jsonpath}"
}

build_url() {
  local svc="$1" path="$2"
  local cluster_ip port node_port
  cluster_ip="$(get_svc_field "$svc" '{.spec.clusterIP}')"
  port="$(get_svc_field "$svc" '{.spec.ports[0].port}')"
  node_port="$(get_svc_field "$svc" '{.spec.ports[0].nodePort}')"

  if [[ "$MODE" == "clusterip" ]]; then
    if [[ -z "$cluster_ip" || "$cluster_ip" == "None" ]]; then
      echo "ERROR: svc/$svc has no clusterIP" >&2
      exit 1
    fi
    printf 'http://%s:%s%s\n' "$cluster_ip" "$port" "$path"
    return
  fi

  if [[ -z "$NODE_IP" ]]; then
    echo "ERROR: MODE=nodeport requires NODE_IP" >&2
    exit 1
  fi
  if [[ -z "$node_port" ]]; then
    echo "ERROR: svc/$svc has no nodePort (service type may not be NodePort)" >&2
    exit 1
  fi
  printf 'http://%s:%s%s\n' "$NODE_IP" "$node_port" "$path"
}

EST_URL="$(build_url "$EST_SVC" "$EST_PATH")"
DET_URL="$(build_url "$DET_SVC" "$DET_PATH")"
FINE_URL="$(build_url "$FINE_SVC" "$FINE_PATH")"

echo "# using kubectl command: $KUBECTL_BIN"
echo "export LOCAL_EST_URL='$EST_URL'"
echo "export LOCAL_DET_URL='$DET_URL'"
echo "export LOCAL_FINE_URL='$FINE_URL'"
