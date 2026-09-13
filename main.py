"""
Root-level entry point for backwards-compatible uvicorn startup.
Usage:
    venv\\Scripts\\python -m uvicorn main:app --host 0.0.0.0 --port 8000

This thin wrapper delegates to backend.app_factory.create_app()
so the old command format keeps working after backend consolidation.
"""
import sys
import os

# Ensure project root is on sys.path so 'backend' package is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.app_factory import app  # noqa: E402,F401

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
