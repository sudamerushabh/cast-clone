"""FastAPI framework plugins — route extraction, Depends() DI, Pydantic deep."""

from app.stages.plugins.fastapi_plugin.pydantic import FastAPIPydanticPlugin
from app.stages.plugins.fastapi_plugin.routes import FastAPIPlugin

__all__ = ["FastAPIPlugin", "FastAPIPydanticPlugin"]
