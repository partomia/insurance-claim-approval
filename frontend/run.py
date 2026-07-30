import os
import subprocess

PORT = os.environ.get("CDSW_APP_PORT", "8090")

os.chdir("/home/cdsw/IC-Portal/frontend")

print(f"Starting frontend dev server on port {PORT}")

subprocess.run(
    [
        "npm",
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        PORT,
                "--strictPort",

    ],
    check=True,
)