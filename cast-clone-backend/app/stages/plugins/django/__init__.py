"""Django framework plugins — Settings, URLs, ORM, DRF."""

from app.stages.plugins.django.settings import DjangoSettingsPlugin

# These will be added as each plugin is implemented:
# from app.stages.plugins.django.urls import DjangoURLsPlugin
# from app.stages.plugins.django.orm import DjangoORMPlugin
# from app.stages.plugins.django.drf import DjangoDRFPlugin

__all__ = ["DjangoSettingsPlugin"]
