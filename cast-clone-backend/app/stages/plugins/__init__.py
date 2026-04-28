"""Framework plugin system for extracting invisible connections from code.

Plugins detect framework usage, extract hidden relationships (DI wiring,
ORM mappings, endpoint routes), and produce new graph nodes and edges.
"""

from app.stages.plugins.alembic_plugin.migrations import AlembicPlugin
from app.stages.plugins.base import (
    FrameworkPlugin,
    LayerRule,
    LayerRules,
    PluginDetectionResult,
    PluginResult,
)
from app.stages.plugins.celery_plugin.tasks import CeleryPlugin
from app.stages.plugins.django.drf import DjangoDRFPlugin
from app.stages.plugins.django.orm import DjangoORMPlugin
from app.stages.plugins.django.settings import DjangoSettingsPlugin
from app.stages.plugins.django.urls import DjangoURLsPlugin
from app.stages.plugins.dotnet.di import ASPNetDIPlugin
from app.stages.plugins.dotnet.entity_framework import EntityFrameworkPlugin
from app.stages.plugins.dotnet.grpc import GRPCPlugin
from app.stages.plugins.dotnet.middleware import ASPNetMiddlewarePlugin
from app.stages.plugins.dotnet.signalr import SignalRPlugin
from app.stages.plugins.dotnet.web import ASPNetWebPlugin
from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin
from app.stages.plugins.fastapi_plugin.routes import FastAPIPlugin
from app.stages.plugins.hibernate.jpa import HibernateJPAPlugin
from app.stages.plugins.registry import (
    PluginRegistry,
    global_registry,
    run_framework_plugins,
)
from app.stages.plugins.spring.data import SpringDataPlugin

# Register all built-in plugins with the global registry
from app.stages.plugins.spring.di import SpringDIPlugin
from app.stages.plugins.spring.events import SpringEventsPlugin
from app.stages.plugins.spring.messaging import SpringMessagingPlugin
from app.stages.plugins.spring.scheduling import SpringSchedulingPlugin
from app.stages.plugins.spring.web import SpringWebPlugin
from app.stages.plugins.sqlalchemy_plugin.models import SQLAlchemyPlugin

global_registry.register(SpringDIPlugin)
global_registry.register(HibernateJPAPlugin)
global_registry.register(SpringWebPlugin)
global_registry.register(SpringDataPlugin)
global_registry.register(SpringEventsPlugin)
global_registry.register(SpringMessagingPlugin)
global_registry.register(SpringSchedulingPlugin)
global_registry.register(ASPNetDIPlugin)
global_registry.register(ASPNetWebPlugin)
global_registry.register(ASPNetMiddlewarePlugin)
global_registry.register(EntityFrameworkPlugin)
global_registry.register(SignalRPlugin)
global_registry.register(GRPCPlugin)
global_registry.register(FastAPIPlugin)
global_registry.register(FastAPIPydanticPlugin)
global_registry.register(SQLAlchemyPlugin)
global_registry.register(DjangoSettingsPlugin)
global_registry.register(DjangoURLsPlugin)
global_registry.register(DjangoORMPlugin)
global_registry.register(DjangoDRFPlugin)
global_registry.register(AlembicPlugin)
global_registry.register(CeleryPlugin)

__all__ = [
    "FrameworkPlugin",
    "LayerRule",
    "LayerRules",
    "PluginDetectionResult",
    "PluginRegistry",
    "PluginResult",
    "AlembicPlugin",
    "CeleryPlugin",
    "FastAPIPlugin",
    "FastAPIPydanticPlugin",
    "SQLAlchemyPlugin",
    "global_registry",
    "run_framework_plugins",
]
