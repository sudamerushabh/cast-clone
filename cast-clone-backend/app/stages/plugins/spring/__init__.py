"""Spring framework plugins — DI, Web, Data, Events, Messaging, Scheduling."""

from app.stages.plugins.spring.data import SpringDataPlugin
from app.stages.plugins.spring.di import SpringDIPlugin
from app.stages.plugins.spring.events import SpringEventsPlugin
from app.stages.plugins.spring.messaging import SpringMessagingPlugin
from app.stages.plugins.spring.scheduling import SpringSchedulingPlugin
from app.stages.plugins.spring.web import SpringWebPlugin

__all__ = [
    "SpringDIPlugin",
    "SpringWebPlugin",
    "SpringDataPlugin",
    "SpringEventsPlugin",
    "SpringMessagingPlugin",
    "SpringSchedulingPlugin",
]
