import logging

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes.auth import router as auth_router
from src.api.routes.chats import router as chat_router
from src.configs.config import config


# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Application
# ------------------------------------------------------------------

app = FastAPI(
    title="Food Ordering AI Agent",
    version="1.0.0",
)


# ------------------------------------------------------------------
# CORS
# ------------------------------------------------------------------

frontend_origins = [
    origin.strip()
    for origin in config.FRONTEND_ORIGINS.split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

app.include_router(
    auth_router,
    prefix="/api/auth",
    tags=["authentication"],
)

app.include_router(
    chat_router,
    prefix="/api/chats",
    tags=["workflows"],
)


# ------------------------------------------------------------------
# Health / Root
# ------------------------------------------------------------------

@app.get("/")
def read_root():
    return {
        "status": "ok",
        "message": "Server is running.",
    }


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "ai-backend",
    }


# ------------------------------------------------------------------
# Local development entry point
# ------------------------------------------------------------------

def main():
    logger.info("Starting AI backend on port %s", config.PORT)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=config.PORT,
    )


if __name__ == "__main__":
    main()