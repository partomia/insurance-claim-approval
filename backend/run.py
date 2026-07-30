import os
import subprocess
os.chdir("/home/cdsw/IC-Portal/backend")
port = os.environ['CDSW_READONLY_PORT'] 
subprocess.run(["uv", "sync", "--frozen"], check=True) 
subprocess.run( [ "uv", "run", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", port, ], check=True, )