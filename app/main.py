"""
FastAPI application entry point.

Run with:
    uvicorn app.main:app --reload --port 8000

In production (Render/Railway/Fly):
    uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 2
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import router
from app.config import get_settings
from app.utils.logger import configure_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown hooks."""
    configure_logging()
    logger = get_logger(__name__)

    settings = get_settings()

    # Fail fast if the LLM provider isn't configured
    try:
        settings.validate_llm_credentials()
    except ValueError as e:
        logger.error("Startup configuration error", extra={"error": str(e)})
        raise

    logger.info(
        "Resume Parser API starting",
        extra={
            "version": __version__,
            "env": settings.app_env,
            "llm_provider": settings.llm_provider,
        },
    )
    yield
    logger.info("Resume Parser API shutting down")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Resume Parser API",
        description=(
            "Extracts structured data from resume PDFs and DOCX files. "
            "Module 1 of the AI Job Application Tracker."
        ),
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(router)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "service": "Resume Parser API",
            "version": __version__,
            "docs": "/docs",
        }

    return app


app = create_app()
