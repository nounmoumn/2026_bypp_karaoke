#!/bin/bash
set -e
cd /workspace/bypp
export BYPP_EXECUTION_MODE=pod
export BYPP_PIPELINE_PYTHON=/root/bypp-venv/bin/python
export PYTHONPATH=/workspace/bypp/backend
export PYTHONIOENCODING=utf-8
if ! pgrep -f '^/root/bypp-venv/bin/python -m uvicorn app.main:app' >/dev/null; then
    nohup /root/bypp-venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 \
        >>/workspace/bypp/server.log 2>&1 </dev/null &
fi
