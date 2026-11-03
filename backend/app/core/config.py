"""
Configuration settings for the Instagram Video Analyzer application.
"""
import os
from pathlib import Path
from typing import List, Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    """Application settings."""
    
    # API Configuration
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    debug: bool = False
    
    # Gemini API
    gemini_model: str = "gemini-3.6-flash"
    gemini_api_key: str
    
    # Database
    database_url: str = "sqlite:///" + (BACKEND_ROOT / "video_analyzer.db").as_posix()
    
    # File Storage
    upload_dir: str = "../data/videos"
    results_dir: str = "../data/results"
    temp_dir: str = "../data/temp"
    max_file_size: int = 100_000_000  # 100MB
    
    # Instagram Configuration
    instagram_username: Optional[str] = None
    instagram_password: Optional[str] = None
    
    # Security
    secret_key: str = "your-secret-key-change-this-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # Redis (for Celery)
    redis_url: str = "redis://localhost:6379/0"
    
    # Logging
    log_level: str = "INFO"
    log_file: str = str(BACKEND_ROOT / "app.log")
    
    # CORS
    allowed_origins: str = "http://localhost:3000,http://localhost:5173"
    
    @field_validator("upload_dir", "results_dir", "temp_dir")
    @classmethod
    def create_directories(cls, v):
        """Create directories if they don't exist."""
        path = Path(v)
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        path.mkdir(parents=True, exist_ok=True)
        return str(path.absolute())
    
    def get_allowed_origins(self) -> List[str]:
        """Get CORS origins as list."""
        if isinstance(self.allowed_origins, str):
            return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]
        return ["http://localhost:3000", "http://localhost:5173"]
    
    class Config:
        env_file = str(Path(__file__).resolve().parents[2] / ".env")
        case_sensitive = False


# Global settings instance
settings = Settings()
