#!/usr/bin/env bash
# Career Workspace — one-command local launcher.
# Uses the project's own .venv (Python 3.12), ignoring any active conda/pyenv
# environment, so no global install or uv sync is needed.
set -euo pipefail

cd "$(dirname "$0")"
PORT="${PORT:-8506}"
URL="http://127.0.0.1:${PORT}"

if [ ! -x ".venv/bin/python" ]; then
    echo "No .venv found — creating it with uv (Python 3.12)…"
    uv sync --python 3.12 --no-editable --reinstall-package tau-job-application
fi

PYTHON_VERSION="$(.venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [ "${PYTHON_VERSION%%.*}" -lt 3 ] || [ "$(.venv/bin/python -c 'import sys; print(sys.version_info >= (3, 12))')" != "True" ]; then
    echo "The .venv uses Python ${PYTHON_VERSION}, but this project needs 3.12+. Recreating…"
    rm -rf .venv
    uv sync --python 3.12 --no-editable --reinstall-package tau-job-application
fi

# Stop a previous instance on the same port, if any.
if lsof -ti ":${PORT}" >/dev/null 2>&1; then
    echo "Stopping the previous server on port ${PORT}…"
    lsof -ti ":${PORT}" | xargs kill 2>/dev/null || true
    sleep 1
fi

echo "Starting Career Workspace at ${URL}"
( sleep 3 && open "${URL}" ) &

exec .venv/bin/python -m streamlit run src/tau_job_application/ui.py \
    --server.address 127.0.0.1 \
    --server.port "${PORT}" \
    --browser.gatherUsageStats false \
    --server.headless true
