"""Framework plugin system for extracting invisible connections from code.

Plugins detect framework usage, extract hidden relationships (DI wiring,
ORM mappings, endpoint routes), and produce new graph nodes and edges.
"""

from app.stages.plugins.dotnet.di import ASPNetDIPlugin
from app.stages.plugins.dotnet.middleware import ASPNetMiddlewarePlugin
from app.stages.plugins.dotnet.web import ASPNetWebPlugin
from app.stages.plugins.django.drf import DjangoDRFPlugin
from app.stages.plugins.django.orm import DjangoORMPlugin
from app.stages.plugins.django.settings import DjangoSettingsPlugin
from app.stages.plugins.django.urls import DjangoURLsPlugin
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRule,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)
from app.stages.plugins.dotnet.entity_framework import EntityFrameworkPlugin
from app.stages.plugins.fastapi_plugin.routes import FastAPIPlugin
from app.stages.plugins.hibernate.jpa import HibernateJPAPlugin
from app.stages.plugins.sqlalchemy_plugin.models import SQLAlchemyPlugin
from app.stages.plugins.registry import (
    PluginRegistry,
    global_registry,
    run_framework_plugins,
)
from app.stages.plugins.spring.data import SpringDataPlugin

# Register all built-in plugins with the global registry
from app.stages.plugins.spring.di import SpringDIPlugin
from app.stages.plugins.spring.web import SpringWebPlugin

global_registry.register(SpringDIPlugin)
global_registry.register(HibernateJPAPlugin)
global_registry.register(SpringWebPlugin)
global_registry.register(SpringDataPlugin)
global_registry.register(ASPNetDIPlugin)
global_registry.register(ASPNetWebPlugin)
global_registry.register(ASPNetMiddlewarePlugin)
global_registry.register(EntityFrameworkPlugin)
global_registry.register(FastAPIPlugin)
global_registry.register(SQLAlchemyPlugin)
global_registry.register(DjangoSettingsPlugin)
global_registry.register(DjangoURLsPlugin)
global_registry.register(DjangoORMPlugin)
global_registry.register(DjangoDRFPlugin)

__all__ = [
    "FrameworkPlugin",
    "LayerRule",
    "LayerRules",
    "PluginDetectionResult",
    "PluginRegistry",
    "PluginResult",
    "FastAPIPlugin",
    "SQLAlchemyPlugin",
    "global_registry",
    "run_framework_plugins",
]
