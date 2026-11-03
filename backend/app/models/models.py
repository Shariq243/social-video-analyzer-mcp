"""
Database models for Instagram Video Analyzer.
"""
import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, Float, Enum, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func

from ..core.database import Base
from .video_job import VideoJob, JobStatus


class AnalysisResult(Base):
    """Analysis result model for detailed storage."""
    __tablename__ = "analysis_results"
    
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String(36), index=True, nullable=False)
    analysis_type = Column(String(50), nullable=False)
    
    # Analysis content
    raw_response = Column(Text)
    structured_analysis = Column(Text)  # JSON string
    transcription = Column(Text)
    summary = Column(Text)
    visual_description = Column(Text)
    
    # Metadata
    model_used = Column(String(100))
    processing_time = Column(Float)
    confidence_score = Column(Float)
    language_detected = Column(String(10))
    
    # File metadata
    video_duration = Column(Float)
    video_format = Column(String(20))
    audio_quality = Column(String(50))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    def __repr__(self):
        return f"<AnalysisResult(job_id='{self.job_id}', type='{self.analysis_type}')>"


class UserSession(Base):
    """User session tracking for analytics."""
    __tablename__ = "user_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(36), unique=True, index=True)
    user_agent = Column(String(500))
    ip_address = Column(String(45))
    
    # Usage statistics
    jobs_created = Column(Integer, default=0)
    jobs_completed = Column(Integer, default=0)
    total_processing_time = Column(Float, default=0.0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_activity = Column(DateTime(timezone=True), server_default=func.now())
    
    def __repr__(self):
        return f"<UserSession(session_id='{self.session_id}')>"


class SystemMetrics(Base):
    """System performance metrics."""
    __tablename__ = "system_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    metric_name = Column(String(100), nullable=False)
    metric_value = Column(Float, nullable=False)
    metric_unit = Column(String(20))
    
    # Context
    job_id = Column(String(36))
    analysis_type = Column(String(50))
    
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    
    def __repr__(self):
        return f"<SystemMetrics(name='{self.metric_name}', value={self.metric_value})>"
