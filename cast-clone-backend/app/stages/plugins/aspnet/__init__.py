"""ASP.NET Core framework plugins — DI, Web, Middleware."""

from app.stages.plugins.aspnet.di import ASPNetDIPlugin
from app.stages.plugins.aspnet.middleware import ASPNetMiddlewarePlugin
from app.stages.plugins.aspnet.web import ASPNetWebPlugin

__all__ = ["ASPNetDIPlugin", "ASPNetWebPlugin", "ASPNetMiddlewarePlugin"]
