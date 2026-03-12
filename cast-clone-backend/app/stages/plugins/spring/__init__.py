"""Spring framework plugins — DI, Web, Data."""

from app.stages.plugins.spring.di import SpringDIPlugin
from app.stages.plugins.spring.web import SpringWebPlugin
from app.stages.plugins.spring.data import SpringDataPlugin

__all__ = ["SpringDIPlugin", "SpringWebPlugin", "SpringDataPlugin"]
