"""Uvicorn 入口：uvicorn app.main:app"""

from .api import create_app

app = create_app()
