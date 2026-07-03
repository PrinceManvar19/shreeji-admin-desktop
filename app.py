"""WSGI entry point for hosted deployments."""

from app_admin import app, create_app


__all__ = ["app", "create_app"]
