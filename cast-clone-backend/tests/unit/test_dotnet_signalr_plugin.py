"""Tests for the SignalR plugin — Hub discovery, method extraction, client events."""

import pytest

from app.models.enums import EdgeKind, NodeKind
from app.models.graph import GraphNode
from app.stages.plugins.dotnet.signalr import SignalRPlugin
from tests.unit.helpers import (
    add_class,
    add_hub_class,
    add_method,
    make_dotnet_context,
)


class TestDetection:
    def test_detects_signalr_via_hub_base_class(self):
        plugin = SignalRPlugin()
        ctx = make_dotnet_context()
        add_class(ctx.graph, "MyApp.ChatHub", "ChatHub", base_class="Hub")
        result = plugin.detect(ctx)
        assert result.is_active

    def test_detects_signalr_via_typed_hub(self):
        plugin = SignalRPlugin()
        ctx = make_dotnet_context()
        add_class(
            ctx.graph,
            "MyApp.NotificationHub",
            "NotificationHub",
            base_class="Hub<INotificationClient>",
        )
        result = plugin.detect(ctx)
        assert result.is_active

    def test_no_detection_without_hubs(self):
        plugin = SignalRPlugin()
        ctx = make_dotnet_context()
        ctx.manifest.detected_frameworks = []
        result = plugin.detect(ctx)
        assert not result.is_active


class TestHubExtraction:
    @pytest.mark.asyncio
    async def test_hub_creates_ws_endpoint(self):
        plugin = SignalRPlugin()
        ctx = make_dotnet_context()
        add_hub_class(
            ctx.graph, "MyApp.ChatHub", "ChatHub", methods=["SendMessage", "JoinGroup"]
        )
        ctx.graph.add_node(
            GraphNode(
                fqn="MyApp.Program",
                name="Program",
                kind=NodeKind.CLASS,
                language="csharp",
                properties={
                    "hub_mappings": [{"hub_type": "ChatHub", "path": "/chatHub"}]
                },
            )
        )
        result = await plugin.extract(ctx)
        endpoints = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoints) == 1
        assert endpoints[0].properties["method"] == "WS"
        assert endpoints[0].properties["path"] == "/chatHub"
        assert endpoints[0].properties["protocol"] == "websocket"

    @pytest.mark.asyncio
    async def test_hub_methods_create_handles_edges(self):
        plugin = SignalRPlugin()
        ctx = make_dotnet_context()
        add_hub_class(
            ctx.graph, "MyApp.ChatHub", "ChatHub", methods=["SendMessage", "JoinGroup"]
        )
        ctx.graph.add_node(
            GraphNode(
                fqn="MyApp.Program",
                name="Program",
                kind=NodeKind.CLASS,
                language="csharp",
                properties={
                    "hub_mappings": [{"hub_type": "ChatHub", "path": "/chatHub"}]
                },
            )
        )
        result = await plugin.extract(ctx)
        handles = [e for e in result.edges if e.kind == EdgeKind.HANDLES]
        handler_fqns = {e.source_fqn for e in handles}
        assert "MyApp.ChatHub.SendMessage" in handler_fqns
        assert "MyApp.ChatHub.JoinGroup" in handler_fqns

    @pytest.mark.asyncio
    async def test_hub_creates_exposes_edge(self):
        plugin = SignalRPlugin()
        ctx = make_dotnet_context()
        add_hub_class(ctx.graph, "MyApp.ChatHub", "ChatHub", methods=["SendMessage"])
        ctx.graph.add_node(
            GraphNode(
                fqn="MyApp.Program",
                name="Program",
                kind=NodeKind.CLASS,
                language="csharp",
                properties={
                    "hub_mappings": [{"hub_type": "ChatHub", "path": "/chatHub"}]
                },
            )
        )
        result = await plugin.extract(ctx)
        exposes = [e for e in result.edges if e.kind == EdgeKind.EXPOSES]
        assert len(exposes) == 1
        assert exposes[0].source_fqn == "MyApp.ChatHub"

    @pytest.mark.asyncio
    async def test_hub_methods_create_entry_points(self):
        plugin = SignalRPlugin()
        ctx = make_dotnet_context()
        add_hub_class(ctx.graph, "MyApp.ChatHub", "ChatHub", methods=["SendMessage"])
        ctx.graph.add_node(
            GraphNode(
                fqn="MyApp.Program",
                name="Program",
                kind=NodeKind.CLASS,
                language="csharp",
                properties={
                    "hub_mappings": [{"hub_type": "ChatHub", "path": "/chatHub"}]
                },
            )
        )
        result = await plugin.extract(ctx)
        assert len(result.entry_points) >= 1
        assert all(ep.kind == "websocket_endpoint" for ep in result.entry_points)

    @pytest.mark.asyncio
    async def test_client_events_create_produces_edges(self):
        plugin = SignalRPlugin()
        ctx = make_dotnet_context()
        add_hub_class(
            ctx.graph,
            "MyApp.ChatHub",
            "ChatHub",
            methods=["SendMessage"],
            client_events=["ReceiveMessage"],
        )
        ctx.graph.add_node(
            GraphNode(
                fqn="MyApp.Program",
                name="Program",
                kind=NodeKind.CLASS,
                language="csharp",
                properties={
                    "hub_mappings": [{"hub_type": "ChatHub", "path": "/chatHub"}]
                },
            )
        )
        result = await plugin.extract(ctx)
        produces = [e for e in result.edges if e.kind == EdgeKind.PRODUCES]
        assert len(produces) >= 1
        assert produces[0].properties.get("event") == "ReceiveMessage"

    @pytest.mark.asyncio
    async def test_strongly_typed_hub_resolves_client_interface(self):
        plugin = SignalRPlugin()
        ctx = make_dotnet_context()
        add_class(
            ctx.graph,
            "MyApp.NotificationHub",
            "NotificationHub",
            base_class="Hub<INotificationClient>",
        )
        add_method(
            ctx.graph, "MyApp.NotificationHub", "SendNotification", return_type="Task"
        )
        add_class(
            ctx.graph,
            "MyApp.INotificationClient",
            "INotificationClient",
            is_interface=True,
        )
        add_method(
            ctx.graph,
            "MyApp.INotificationClient",
            "ReceiveNotification",
            return_type="Task",
        )
        add_method(
            ctx.graph, "MyApp.INotificationClient", "UserJoined", return_type="Task"
        )
        ctx.graph.add_node(
            GraphNode(
                fqn="MyApp.Program",
                name="Program",
                kind=NodeKind.CLASS,
                language="csharp",
                properties={
                    "hub_mappings": [
                        {"hub_type": "NotificationHub", "path": "/notifications"}
                    ]
                },
            )
        )
        result = await plugin.extract(ctx)
        produces = [e for e in result.edges if e.kind == EdgeKind.PRODUCES]
        event_names = {e.properties.get("event") for e in produces}
        assert "ReceiveNotification" in event_names
        assert "UserJoined" in event_names

    @pytest.mark.asyncio
    async def test_hub_classified_as_presentation(self):
        plugin = SignalRPlugin()
        ctx = make_dotnet_context()
        add_hub_class(ctx.graph, "MyApp.ChatHub", "ChatHub", methods=["SendMessage"])
        ctx.graph.add_node(
            GraphNode(
                fqn="MyApp.Program",
                name="Program",
                kind=NodeKind.CLASS,
                language="csharp",
                properties={
                    "hub_mappings": [{"hub_type": "ChatHub", "path": "/chatHub"}]
                },
            )
        )
        result = await plugin.extract(ctx)
        assert result.layer_assignments.get("MyApp.ChatHub") == "Presentation"
