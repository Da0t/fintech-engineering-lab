"""Local engines plus an isolated public-demo deployment mode."""
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from clearledger.api import router as ledger_router
from marketlab.api import router as market_router
from public_demo import router as public_router

ROOT = Path(__file__).resolve().parent
def create_app(public=None):
    if public is None:
        public = os.environ.get("PUBLIC_DEMO") == "1" or os.environ.get("VERCEL") == "1"
    application = FastAPI(title="Fintech Engineering Lab", version="0.2.0", description="Synthetic financial sandboxes. No real funds or live trading.")
    if public:
        application.include_router(public_router)
    else:
        application.include_router(ledger_router)
        application.include_router(market_router)
    application.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
    application.add_api_route("/", index, include_in_schema=False)
    application.add_api_route("/clearledger", index, include_in_schema=False)
    application.add_api_route("/marketlab", index, include_in_schema=False)
    application.add_api_route("/api/config", lambda: {"public_demo": public})
    application.add_api_route("/health", lambda: {"status":"ok", "mode":"public-isolated-sandbox" if public else "local-synthetic-demo"})
    return application


def index():
    return FileResponse(ROOT / "web" / "index.html")


app = create_app()
