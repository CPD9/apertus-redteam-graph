#!/usr/bin/env bash
# Stop the model servers, then the pod itself, so billing ends. Run on the pod:
#   ssh -p <PORT> root@<IP> 'bash /workspace/stop_pod.sh'
# The pod's own RunPod credentials live in the environment of PID 1; nothing is typed in.
set -euo pipefail
pkill -f "[v]llm serve" || true
sleep 3
nvidia-smi --query-gpu=memory.used --format=csv,noheader
set -a
eval "$(tr '\0' '\n' < /proc/1/environ | grep -E '^(RUNPOD_API_KEY|RUNPOD_POD_ID)=')"
set +a
runpodctl stop pod "$RUNPOD_POD_ID"
