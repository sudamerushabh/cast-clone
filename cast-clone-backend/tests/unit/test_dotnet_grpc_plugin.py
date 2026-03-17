"""Tests for the gRPC plugin — service class discovery, RPC methods, endpoint mapping."""

import pytest

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphNode
from app.stages.plugins.dotnet.grpc import GRPCPlugin
from tests.unit.helpers import add_class, add_grpc_service, make_dotnet_context


class TestDetection:
    def test_detects_grpc_via_base_class_pattern(self):
        plugin = GRPCPlugin()
        ctx = make_dotnet_context()
        add_class(
            ctx.graph,
            "MyApp.GreeterService",
            "GreeterService",
            base_class="Greeter.GreeterBase",
        )
        result = plugin.detect(ctx)
        assert result.is_active

    def test_no_false_positive_on_generic_base(self):
        plugin = GRPCPlugin()
        ctx = make_dotnet_context()
        ctx.manifest.detected_frameworks = []
        add_class(
            ctx.graph,
            "MyApp.MyProfile",
            "MyProfile",
            base_class="AutoMapper.ProfileBase",
        )
        result = plugin.detect(ctx)
        assert not result.is_active

    def test_no_detection_without_grpc_classes(self):
        plugin = GRPCPlugin()
        ctx = make_dotnet_context()
        ctx.manifest.detected_frameworks = []
        result = plugin.detect(ctx)
        assert not result.is_active


class TestGRPCExtraction:
    @pytest.mark.asyncio
    async def test_grpc_service_creates_endpoint_per_method(self):
        plugin = GRPCPlugin()
        ctx = make_dotnet_context()
        add_grpc_service(
            ctx.graph,
            "MyApp.GreeterService",
            "GreeterService",
            base_class="Greeter.GreeterBase",
            override_methods=[
                {
                    "name": "SayHello",
                    "request_type": "HelloRequest",
                    "response_type": "Task<HelloReply>",
                },
                {
                    "name": "SayGoodbye",
                    "request_type": "GoodbyeRequest",
                    "response_type": "Task<GoodbyeReply>",
                },
            ],
        )
        ctx.graph.add_node(
            GraphNode(
                fqn="MyApp.Program",
                name="Program",
                kind=NodeKind.CLASS,
                language="csharp",
                properties={
                    "grpc_mappings": [{"service_type": "GreeterService"}]
                },
            )
        )
        result = await plugin.extract(ctx)
        endpoints = [n for n in result.nodes if n.kind == NodeKind.API_ENDPOINT]
        assert len(endpoints) == 2
        assert all(ep.properties["method"] == "GRPC" for ep in endpoints)
        paths = {ep.properties["path"] for ep in endpoints}
        assert "/Greeter/SayHello" in paths
        assert "/Greeter/SayGoodbye" in paths

    @pytest.mark.asyncio
    async def test_grpc_creates_handles_and_exposes_edges(self):
        plugin = GRPCPlugin()
        ctx = make_dotnet_context()
        add_grpc_service(
            ctx.graph,
            "MyApp.GreeterService",
            "GreeterService",
            base_class="Greeter.GreeterBase",
            override_methods=[
                {
                    "name": "SayHello",
                    "request_type": "HelloRequest",
                    "response_type": "Task<HelloReply>",
                },
            ],
        )
        ctx.graph.add_node(
            GraphNode(
                fqn="MyApp.Program",
                name="Program",
                kind=NodeKind.CLASS,
                language="csharp",
                properties={
                    "grpc_mappings": [{"service_type": "GreeterService"}]
                },
            )
        )
        result = await plugin.extract(ctx)
        handles = [e for e in result.edges if e.kind == EdgeKind.HANDLES]
        assert len(handles) == 1
        assert handles[0].source_fqn == "MyApp.GreeterService.SayHello"
        exposes = [e for e in result.edges if e.kind == EdgeKind.EXPOSES]
        assert len(exposes) >= 1
        assert exposes[0].source_fqn == "MyApp.GreeterService"

    @pytest.mark.asyncio
    async def test_grpc_creates_entry_points(self):
        plugin = GRPCPlugin()
        ctx = make_dotnet_context()
        add_grpc_service(
            ctx.graph,
            "MyApp.GreeterService",
            "GreeterService",
            base_class="Greeter.GreeterBase",
            override_methods=[
                {
                    "name": "SayHello",
                    "request_type": "HelloRequest",
                    "response_type": "Task<HelloReply>",
                },
            ],
        )
        ctx.graph.add_node(
            GraphNode(
                fqn="MyApp.Program",
                name="Program",
                kind=NodeKind.CLASS,
                language="csharp",
                properties={
                    "grpc_mappings": [{"service_type": "GreeterService"}]
                },
            )
        )
        result = await plugin.extract(ctx)
        assert len(result.entry_points) >= 1
        assert all(ep.kind == "grpc_endpoint" for ep in result.entry_points)

    @pytest.mark.asyncio
    async def test_grpc_service_classified_as_presentation(self):
        plugin = GRPCPlugin()
        ctx = make_dotnet_context()
        add_grpc_service(
            ctx.graph,
            "MyApp.GreeterService",
            "GreeterService",
            base_class="Greeter.GreeterBase",
            override_methods=[
                {
                    "name": "SayHello",
                    "request_type": "HelloRequest",
                    "response_type": "Task<HelloReply>",
                },
            ],
        )
        ctx.graph.add_node(
            GraphNode(
                fqn="MyApp.Program",
                name="Program",
                kind=NodeKind.CLASS,
                language="csharp",
                properties={
                    "grpc_mappings": [{"service_type": "GreeterService"}]
                },
            )
        )
        result = await plugin.extract(ctx)
        assert result.layer_assignments.get("MyApp.GreeterService") == "Presentation"
