import os
import subprocess
import signal
import sys
import time

PROJECT_ROOT = "/home/cdsw/IC-Portal"

FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")

APP_PORT = os.environ.get("CDSW_APP_PORT", "8090")
BACKEND_PORT =  "5550"

print(f"Frontend: http://127.0.0.1:{APP_PORT}")
print(f"Backend : http://127.0.0.1:{BACKEND_PORT}")

# Install backend dependencies
subprocess.run(
    ["uv", "sync", "--frozen"],
    cwd=BACKEND_DIR,
    check=True,
)

backend = subprocess.Popen(
    [
        "uv",
        "run",
        "uvicorn",
        "main:app",
        "--host",
        "127.0.0.1",
        "--port",
        BACKEND_PORT,
    ],
    cwd=BACKEND_DIR,
)

frontend = subprocess.Popen(
    [
        "npm",
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        APP_PORT,
        "--strictPort",
    ],
    cwd=FRONTEND_DIR,
)

processes = [backend, frontend]


def shutdown(*args):
    print("\nStopping services...")
    for p in processes:
        if p.poll() is None:
            p.terminate()

    time.sleep(2)

    for p in processes:
        if p.poll() is None:
            p.kill()

    sys.exit(0)


signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

try:
    while True:
        for p in processes:
            if p.poll() is not None:
                shutdown()
        time.sleep(1)
except KeyboardInterrupt:
    shutdown()