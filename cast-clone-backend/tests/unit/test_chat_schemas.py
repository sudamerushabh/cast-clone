# tests/unit/test_chat_schemas.py
import pytest
from app.schemas.chat import ChatRequest, PageContext


class TestPageContext:
    def test_minimal(self):
        ctx = PageContext(page="dashboard")
        assert ctx.page == "dashboard"
        assert ctx.selected_node_fqn is None

    def test_full(self):
        ctx = PageContext(
            page="graph_explorer",
            selected_node_fqn="com.app.OrderService",
            view="architecture",
            level="class",
        )
        assert ctx.selected_node_fqn == "com.app.OrderService"


class TestChatRequest:
    def test_minimal(self):
        req = ChatRequest(message="What does OrderService do?")
        assert req.message == "What does OrderService do?"
        assert req.history == []
        assert req.include_page_context is True
        assert req.page_context is None

    def test_with_context(self):
        req = ChatRequest(
            message="Explain this",
            page_context=PageContext(page="graph_explorer", selected_node_fqn="com.app.X"),
            include_page_context=True,
            history=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
        )
        assert req.page_context.selected_node_fqn == "com.app.X"
        assert len(req.history) == 2

    def test_history_max_10(self):
        history = [{"role": "user", "content": f"msg {i}"} for i in range(12)]
        req = ChatRequest(message="latest", history=history)
        assert len(req.history) == 10  # Truncated to last 10
