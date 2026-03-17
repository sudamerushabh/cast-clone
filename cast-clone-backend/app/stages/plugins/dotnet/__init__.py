"""ASP.NET Core / .NET framework plugins — DI, Web, Middleware, Entity Framework, SignalR, gRPC."""

from app.stages.plugins.dotnet.di import ASPNetDIPlugin
from app.stages.plugins.dotnet.entity_framework import EntityFrameworkPlugin
from app.stages.plugins.dotnet.middleware import ASPNetMiddlewarePlugin
from app.stages.plugins.dotnet.signalr import SignalRPlugin
from app.stages.plugins.dotnet.web import ASPNetWebPlugin

__all__ = [
    "ASPNetDIPlugin",
    "ASPNetWebPlugin",
    "ASPNetMiddlewarePlugin",
    "EntityFrameworkPlugin",
    "SignalRPlugin",
]
