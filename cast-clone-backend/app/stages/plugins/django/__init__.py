"""Django framework plugins — Settings, URLs, ORM, DRF."""

from app.stages.plugins.django.settings import DjangoSettingsPlugin
from app.stages.plugins.django.urls import DjangoURLsPlugin

# These will be added as each plugin is implemented:
# from app.stages.plugins.django.orm import DjangoORMPlugin
# from app.stages.plugins.django.drf import DjangoDRFPlugin

__all__ = ["DjangoSettingsPlugin", "DjangoURLsPlugin"]
