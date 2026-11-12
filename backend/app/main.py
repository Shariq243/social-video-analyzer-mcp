"""
Main FastAPI application for Social Video Analyzer.
"""
import logging
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .core.config import settings
from .database import init_db
from .security import BackendBoundary, SecretFilter

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        RotatingFileHandler(settings.log_file, maxBytes=2_000_000, backupCount=2, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)
# Provider URLs can carry signed media query parameters.
logging.getLogger('httpx').setLevel(logging.WARNING)
for handler in logging.getLogger().handlers:
    handler.addFilter(SecretFilter())

from .api.routes import video_router, jobs_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    """
    # Startup
    if len(settings.backend_api_key) < 32:
        raise RuntimeError('Set BACKEND_API_KEY to a random value of at least 32 characters, or use Windows Setup.')
    logger.info("Starting Social Video Analyzer API")
    
    # Initialize database
    init_db()
    logger.info("Database initialized")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Social Video Analyzer API")


# Create FastAPI application
app = FastAPI(
    title="Social Video Analyzer",
    description="Public social post and video analysis with Ollama vision and Gemini video analysis",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.add_middleware(BackendBoundary)
app.include_router(video_router, prefix="/api")
app.include_router(jobs_router, prefix="/api")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Social Video Analyzer API",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": "2025-01-27T23:54:00Z"
    }


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
        log_level=settings.log_level.lower()
    )
