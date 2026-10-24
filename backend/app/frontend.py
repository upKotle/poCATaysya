"""Раздача готового интерфейса из единого Docker-образа."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def mount_frontend(app: FastAPI, directory: Path) -> None:
    # При разработке без сборки frontend обслуживает Vite.
    # Монтировать после API, чтобы статика не перехватывала его запросы.
    if directory.is_dir():
        app.mount('/', StaticFiles(directory=directory, html=True), name='frontend')
