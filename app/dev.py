"""Run all four processes on a laptop with one command: uv run python -m app.dev

PORT=8010 uv run python -m app.dev   if something else already uses 8000
"""

import os
import signal
import subprocess
import sys

PORT = os.environ.get("PORT", "8000")

CMDS = {
    "local": [sys.executable, "-m", "uvicorn", "app.main:app", "--port", PORT],
    "local-1": [sys.executable, "-m", "app.worker"],
    "local-2": [sys.executable, "-m", "app.worker"],
    "local-t": [sys.executable, "-m", "app.ticker"],
}

procs = []
for name, cmd in CMDS.items():
    env = {
        **os.environ,
        "TASK_NAME": name,
        "TICK_FOREVER": "1",
        "HUB_URL": f"http://localhost:{PORT}",
    }
    procs.append(subprocess.Popen(cmd, env=env))
try:
    for p in procs:
        p.wait()
except KeyboardInterrupt:
    for p in procs:
        p.send_signal(signal.SIGINT)
