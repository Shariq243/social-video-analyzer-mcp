"""Compatibility exports for the canonical database and mapped models."""
from .core.database import Base, engine, SessionLocal, get_db, create_tables
from . import models
from sqlalchemy import text

init_db = create_tables

def check_db_health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
