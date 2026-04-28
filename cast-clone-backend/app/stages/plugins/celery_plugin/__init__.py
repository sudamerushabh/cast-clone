"""Celery plugin — task discovery, queue extraction, producer linking."""

from app.stages.plugins.celery_plugin.tasks import CeleryPlugin

__all__ = ["CeleryPlugin"]
