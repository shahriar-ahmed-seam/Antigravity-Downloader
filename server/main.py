import os
import sys
from pathlib import Path
import uvicorn

# Add current directory to python path
current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(current_dir))

# Ensure the frontend directory exists so mount doesn't fail
frontend_dir = current_dir / "frontend"
frontend_dir.mkdir(exist_ok=True)

if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", 8000))
    
    print(f"==================================================")
    print(f" Starting Novel Downloader FastAPI Web Server")
    print(f" URL: http://{host}:{port}")
    print(f"==================================================")
    
    uvicorn.run("backend.app:app", host=host, port=port, reload=True)
