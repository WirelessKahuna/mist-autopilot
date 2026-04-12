import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from routers import org_router, modules_router, credentials_router

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="Mist Autopilot",
    description="Self-driving network org health review powered by Mist APIs",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://frontend:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(org_router)
app.include_router(modules_router)
app.include_router(credentials_router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
