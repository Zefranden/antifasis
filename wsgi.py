"""Punto de entrada WSGI para Gunicorn/Render."""

from antifasis.api import create_app

app = create_app()
