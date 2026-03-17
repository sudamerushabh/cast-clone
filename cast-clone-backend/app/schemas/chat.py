# app/schemas/chat.py
"""Request/response models for the AI chat endpoint."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class PageContext(BaseModel):
    """Describes what page/view the user is currently on."""

    page: str  # "graph_explorer", "pr_detail", "dashboard"
    selected_node_fqn: str | None = None
    view: str | None = None  # "architecture", "dependency", "transaction"
    level: str | None = None  # "module", "class", "method"
    pr_analysis_id: str | None = None


class ChatRequest(BaseModel):
    """Incoming chat message from the frontend."""

    message: str = Field(..., min_length=1, max_length=5000)
    history: list[dict] = Field(default_factory=list)
    page_context: PageContext | None = None
    include_page_context: bool = True
    tone: str = "normal"  # "detailed_technical", "normal", "concise"

    @model_validator(mode="after")
    def trim_history(self) -> ChatRequest:
        """Keep only the last 10 conversation turns."""
        if len(self.history) > 10:
            self.history = self.history[-10:]
        return self
