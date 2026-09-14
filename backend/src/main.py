"""FastAPI application bootstrap."""

import logging

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.router import api_router
from src.configs.config import config
from src.observability.health import get_readiness
from src.observability.middleware import ObservabilityMiddleware
from src.observability.security_headers import SecurityHeadersMiddleware


logger = logging.getLogger(__name__)


def _frontend_origins() -> list[str]:
    """Return configured frontend origins with surrounding whitespace removed."""
    return [
        origin.strip()
        for origin in config.FRONTEND_ORIGINS.split(",")
        if origin.strip()
    ]


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Food Ordering AI Agent",
        version="1.0.0",
    )

    app.add_middleware(ObservabilityMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_frontend_origins(),
        allow_credentials=True,
        allow_methods=[
            "GET",
            "POST",
            "PATCH",
            "DELETE",
            "OPTIONS",
        ],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept",
            "X-Request-ID",
        ],
    )

    app.include_router(api_router)

    @app.get("/")
    def read_root():
        return {
            "status": "ok",
            "message": "Server is running.",
        }

    @app.get("/ready")
    def readiness():
        return get_readiness()

    @app.get("/health")
    def health_check():
        return {
            "status": "ok",
            "service": "ai-backend",
        }

    return app


app = create_app()


def main() -> None:
    """Run the application with the configured server settings."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info(
        "Starting AI backend on port %s",
        config.PORT,
    )

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=config.PORT,
    )


if __name__ == "__main__":
    main()
