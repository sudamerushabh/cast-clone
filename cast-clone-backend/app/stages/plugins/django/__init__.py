"""Django framework plugins — Settings, URLs, ORM, DRF."""

from app.stages.plugins.django.drf import DjangoDRFPlugin
from app.stages.plugins.django.orm import DjangoORMPlugin
from app.stages.plugins.django.settings import DjangoSettingsPlugin
from app.stages.plugins.django.urls import DjangoURLsPlugin

__all__ = [
    "DjangoSettingsPlugin",
    "DjangoURLsPlugin",
    "DjangoORMPlugin",
    "DjangoDRFPlugin",
]
