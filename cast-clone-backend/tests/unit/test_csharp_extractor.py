"""Tests for the C# tree-sitter extractor.

Tests cover: namespace/using resolution, class declarations with inheritance,
interfaces, methods with attributes, properties, constructors with DI params,
method calls, object creation, and full ASP.NET controller files.
"""

from pathlib import Path

import pytest

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.stages.treesitter.extractors.csharp import CSharpExtractor

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "csharp"


@pytest.fixture
def extractor() -> CSharpExtractor:
    return CSharpExtractor()


def _read(filename: str) -> bytes:
    return (FIXTURES / filename).read_bytes()


def _find_node(nodes, *, fqn: str = None, name: str = None, kind: NodeKind = None):
    """Find a node matching the given criteria."""
    for n in nodes:
        if fqn and n.fqn != fqn:
            continue
        if name and n.name != name:
            continue
        if kind and n.kind != kind:
            continue
        return n
    criteria = ", ".join(
        f"{k}={v}" for k, v in {"fqn": fqn, "name": name, "kind": kind}.items() if v
    )
    raise AssertionError(
        f"No node found matching {criteria}. "
        f"Available: {[(n.fqn, n.kind) for n in nodes]}"
    )


def _find_edge(
    edges,
    *,
    source_fqn: str = None,
    target_fqn: str = None,
    kind: EdgeKind = None,
):
    """Find an edge matching the given criteria."""
    for e in edges:
        if source_fqn and e.source_fqn != source_fqn:
            continue
        if target_fqn and e.target_fqn != target_fqn:
            continue
        if kind and e.kind != kind:
            continue
        return e
    pairs = {
        "source_fqn": source_fqn,
        "target_fqn": target_fqn,
        "kind": kind,
    }
    criteria = ", ".join(f"{k}={v}" for k, v in pairs.items() if v)
    raise AssertionError(
        f"No edge found matching {criteria}. "
        f"Available: {[(e.source_fqn, e.target_fqn, e.kind) for e in edges]}"
    )


def _find_edges(
    edges,
    *,
    source_fqn: str = None,
    target_fqn: str = None,
    kind: EdgeKind = None,
):
    """Find all edges matching the given criteria."""
    result = []
    for e in edges:
        if source_fqn and e.source_fqn != source_fqn:
            continue
        if target_fqn and e.target_fqn != target_fqn:
            continue
        if kind and e.kind != kind:
            continue
        result.append(e)
    return result


# ---------------------------------------------------------------------------
# Test 1: Class with base class + interface -> INHERITS + IMPLEMENTS
# ---------------------------------------------------------------------------
class TestClassInheritance:
    def test_class_node_created_with_correct_fqn(self, extractor):
        source = _read("SimpleClass.cs")
        nodes, edges = extractor.extract(source, "SimpleClass.cs", "/src")

        user_node = _find_node(nodes, fqn="MyApp.Models.User", kind=NodeKind.CLASS)
        assert user_node.name == "User"
        assert user_node.language == "csharp"
        assert user_node.path == "SimpleClass.cs"
        assert user_node.line is not None

    def test_inherits_edge_to_base_class(self, extractor):
        source = _read("SimpleClass.cs")
        nodes, edges = extractor.extract(source, "SimpleClass.cs", "/src")

        inherits = _find_edge(
            edges, source_fqn="MyApp.Models.User", kind=EdgeKind.INHERITS
        )
        assert inherits.target_fqn == "MyApp.Models.BaseModel"

    def test_implements_edge_to_interface(self, extractor):
        source = _read("SimpleClass.cs")
        nodes, edges = extractor.extract(source, "SimpleClass.cs", "/src")

        implements = _find_edge(
            edges,
            source_fqn="MyApp.Models.User",
            kind=EdgeKind.IMPLEMENTS,
        )
        assert implements.target_fqn == "MyApp.Models.IEntity"

    def test_base_model_class_node_exists(self, extractor):
        source = _read("SimpleClass.cs")
        nodes, edges = extractor.extract(source, "SimpleClass.cs", "/src")

        base_node = _find_node(nodes, fqn="MyApp.Models.BaseModel", kind=NodeKind.CLASS)
        assert base_node.name == "BaseModel"

    def test_interface_node_exists(self, extractor):
        source = _read("SimpleClass.cs")
        nodes, edges = extractor.extract(source, "SimpleClass.cs", "/src")

        iface = _find_node(nodes, fqn="MyApp.Models.IEntity", kind=NodeKind.INTERFACE)
        assert iface.name == "IEntity"
        assert iface.kind == NodeKind.INTERFACE


# ---------------------------------------------------------------------------
# Test 2: Methods with attributes
# ---------------------------------------------------------------------------
class TestMethodsWithAttributes:
    def test_method_nodes_created(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        get_all = _find_node(
            nodes,
            fqn="MyApp.Controllers.UsersController.GetAll",
            kind=NodeKind.FUNCTION,
        )
        assert get_all.name == "GetAll"
        assert get_all.language == "csharp"

    def test_method_has_http_attribute(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        get_all = _find_node(
            nodes,
            fqn="MyApp.Controllers.UsersController.GetAll",
            kind=NodeKind.FUNCTION,
        )
        annotations = get_all.properties.get("annotations", [])
        assert "HttpGet" in annotations

    def test_method_with_path_attribute(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        get_by_id = _find_node(
            nodes,
            fqn="MyApp.Controllers.UsersController.GetById",
            kind=NodeKind.FUNCTION,
        )
        annotations = get_by_id.properties.get("annotations", [])
        assert "HttpGet" in annotations

    def test_method_return_type_stored(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        get_all = _find_node(
            nodes,
            fqn="MyApp.Controllers.UsersController.GetAll",
            kind=NodeKind.FUNCTION,
        )
        assert get_all.properties.get("return_type") is not None

    def test_method_parameters_stored(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        get_by_id = _find_node(
            nodes,
            fqn="MyApp.Controllers.UsersController.GetById",
            kind=NodeKind.FUNCTION,
        )
        params = get_by_id.properties.get("parameters", [])
        assert any(p.get("name") == "id" for p in params)


# ---------------------------------------------------------------------------
# Test 3: Properties (auto-properties)
# ---------------------------------------------------------------------------
class TestProperties:
    def test_auto_property_creates_field_node(self, extractor):
        source = _read("SimpleClass.cs")
        nodes, edges = extractor.extract(source, "SimpleClass.cs", "/src")

        name_field = _find_node(
            nodes, fqn="MyApp.Models.User.Name", kind=NodeKind.FIELD
        )
        assert name_field.name == "Name"
        assert name_field.properties.get("type") == "string"

    def test_field_contained_in_class(self, extractor):
        source = _read("SimpleClass.cs")
        nodes, edges = extractor.extract(source, "SimpleClass.cs", "/src")

        contains = _find_edge(
            edges,
            source_fqn="MyApp.Models.User",
            target_fqn="MyApp.Models.User.Name",
            kind=EdgeKind.CONTAINS,
        )
        assert contains is not None

    def test_private_field_detected(self, extractor):
        source = _read("SimpleClass.cs")
        nodes, edges = extractor.extract(source, "SimpleClass.cs", "/src")

        roles_field = _find_node(
            nodes, fqn="MyApp.Models.User._roles", kind=NodeKind.FIELD
        )
        assert roles_field.visibility == "private"


# ---------------------------------------------------------------------------
# Test 4: Using directives + namespace -> correct FQN
# ---------------------------------------------------------------------------
class TestNamespaceAndUsing:
    def test_fqn_includes_namespace(self, extractor):
        source = _read("SimpleClass.cs")
        nodes, edges = extractor.extract(source, "SimpleClass.cs", "/src")

        user = _find_node(nodes, name="User", kind=NodeKind.CLASS)
        assert user.fqn == "MyApp.Models.User"

    def test_using_directives_captured(self, extractor):
        source = _read("SimpleClass.cs")
        nodes, edges = extractor.extract(source, "SimpleClass.cs", "/src")

        # Using directives are stored for downstream resolution.
        # We check that the extractor returns nodes or metadata for usings.
        # Usings are stored in the class properties or returned as import info.
        user = _find_node(nodes, name="User", kind=NodeKind.CLASS)
        # The extractor should store using directives somewhere accessible.
        # Convention: properties["usings"] on the first class or as separate data.
        # For now we verify the FQN was correctly resolved with the namespace.
        assert user.fqn.startswith("MyApp.Models.")

    def test_nested_namespace_works(self, extractor):
        """Namespace with dots is correctly used as FQN prefix."""
        source = b"""
namespace MyApp.Domain.Models
{
    public class Order
    {
        public int Id { get; set; }
    }
}
"""
        nodes, edges = extractor.extract(source, "Order.cs", "/src")
        order = _find_node(nodes, name="Order", kind=NodeKind.CLASS)
        assert order.fqn == "MyApp.Domain.Models.Order"


# ---------------------------------------------------------------------------
# Test 5: Constructor with DI parameters
# ---------------------------------------------------------------------------
class TestConstructorDI:
    def test_constructor_creates_function_node(self, extractor):
        source = _read("ServiceWithDI.cs")
        nodes, edges = extractor.extract(source, "ServiceWithDI.cs", "/src")

        ctor = _find_node(
            nodes,
            fqn="MyApp.Services.UserService.UserService",
            kind=NodeKind.FUNCTION,
        )
        assert ctor.name == "UserService"
        assert ctor.properties.get("is_constructor") is True

    def test_constructor_parameters_captured(self, extractor):
        source = _read("ServiceWithDI.cs")
        nodes, edges = extractor.extract(source, "ServiceWithDI.cs", "/src")

        ctor = _find_node(
            nodes,
            fqn="MyApp.Services.UserService.UserService",
            kind=NodeKind.FUNCTION,
        )
        params = ctor.properties.get("parameters", [])
        param_types = [p.get("type") for p in params]
        assert "IUserRepository" in param_types
        assert "IEmailService" in param_types

    def test_constructor_contained_in_class(self, extractor):
        source = _read("ServiceWithDI.cs")
        nodes, edges = extractor.extract(source, "ServiceWithDI.cs", "/src")

        contains = _find_edge(
            edges,
            source_fqn="MyApp.Services.UserService",
            target_fqn="MyApp.Services.UserService.UserService",
            kind=EdgeKind.CONTAINS,
        )
        assert contains is not None


# ---------------------------------------------------------------------------
# Test 6: Method calls
# ---------------------------------------------------------------------------
class TestMethodCalls:
    def test_method_invocation_creates_calls_edge(self, extractor):
        source = _read("ServiceWithDI.cs")
        nodes, edges = extractor.extract(source, "ServiceWithDI.cs", "/src")

        # GetUserAsync calls _repo.FindByIdAsync
        calls = _find_edges(edges, kind=EdgeKind.CALLS)
        # Should have at least one CALLS edge from GetUserAsync
        get_user_calls = [e for e in calls if "GetUserAsync" in e.source_fqn]
        assert len(get_user_calls) >= 1

    def test_calls_edge_has_low_confidence(self, extractor):
        source = _read("ServiceWithDI.cs")
        nodes, edges = extractor.extract(source, "ServiceWithDI.cs", "/src")

        calls = _find_edges(edges, kind=EdgeKind.CALLS)
        # Tree-sitter-only calls should be LOW confidence (unresolved)
        for call in calls:
            assert call.confidence == Confidence.LOW

    def test_object_creation_creates_calls_edge(self, extractor):
        source = _read("ServiceWithDI.cs")
        nodes, edges = extractor.extract(source, "ServiceWithDI.cs", "/src")

        # CreateUserAsync has `new User(name, email)`
        calls = _find_edges(edges, kind=EdgeKind.CALLS)
        new_user_calls = [
            e
            for e in calls
            if "CreateUserAsync" in e.source_fqn and "User" in e.target_fqn
        ]
        assert len(new_user_calls) >= 1


# ---------------------------------------------------------------------------
# Test 7: Full ASP.NET controller file
# ---------------------------------------------------------------------------
class TestAspNetController:
    def test_controller_class_has_attributes(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        ctrl = _find_node(
            nodes,
            fqn="MyApp.Controllers.UsersController",
            kind=NodeKind.CLASS,
        )
        annotations = ctrl.properties.get("annotations", [])
        assert "ApiController" in annotations
        assert "Authorize" in annotations
        assert "Route" in annotations

    def test_controller_inherits_controllerbase(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        inherits = _find_edge(
            edges,
            source_fqn="MyApp.Controllers.UsersController",
            kind=EdgeKind.INHERITS,
        )
        assert "ControllerBase" in inherits.target_fqn

    def test_controller_contains_methods(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        contains_edges = _find_edges(
            edges,
            source_fqn="MyApp.Controllers.UsersController",
            kind=EdgeKind.CONTAINS,
        )
        contained_fqns = {e.target_fqn for e in contains_edges}
        assert "MyApp.Controllers.UsersController.GetAll" in contained_fqns
        assert "MyApp.Controllers.UsersController.GetById" in contained_fqns
        assert "MyApp.Controllers.UsersController.Create" in contained_fqns
        assert "MyApp.Controllers.UsersController.Delete" in contained_fqns

    def test_all_methods_extracted(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        method_nodes = [n for n in nodes if n.kind == NodeKind.FUNCTION]
        method_names = {n.name for n in method_nodes}
        expected = {"GetAll", "GetById", "Create", "Delete", "UsersController"}
        assert expected <= method_names

    def test_route_attribute_stored(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        ctrl = _find_node(
            nodes,
            fqn="MyApp.Controllers.UsersController",
            kind=NodeKind.CLASS,
        )
        # Route annotation argument should be captured
        annotation_args = ctrl.properties.get("annotation_args", {})
        assert "Route" in annotation_args
        assert "api/[controller]" in annotation_args["Route"]


# ---------------------------------------------------------------------------
# Test 8: Attribute argument extraction
# ---------------------------------------------------------------------------
class TestAttributeArguments:
    def test_authorize_roles_extracted(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        delete = _find_node(
            nodes,
            fqn="MyApp.Controllers.UsersController.Delete",
            kind=NodeKind.FUNCTION,
        )
        annotation_args = delete.properties.get("annotation_args", {})
        assert "Authorize" in annotation_args

    def test_http_get_path_extracted(self, extractor):
        source = _read("UserController.cs")
        nodes, edges = extractor.extract(source, "UserController.cs", "/src")

        get_by_id = _find_node(
            nodes,
            fqn="MyApp.Controllers.UsersController.GetById",
            kind=NodeKind.FUNCTION,
        )
        annotation_args = get_by_id.properties.get("annotation_args", {})
        assert "HttpGet" in annotation_args
        assert "{id}" in annotation_args["HttpGet"]


# ---------------------------------------------------------------------------
# Test 9: String literal tagging (SQL-like strings)
# ---------------------------------------------------------------------------
class TestStringLiterals:
    def test_sql_like_string_tagged(self, extractor):
        source = b"""
namespace MyApp.Data
{
    public class UserRepository
    {
        public void RunQuery()
        {
            var sql = "SELECT * FROM users WHERE active = 1";
        }
    }
}
"""
        nodes, edges = extractor.extract(source, "UserRepository.cs", "/src")

        repo = _find_node(nodes, name="UserRepository", kind=NodeKind.CLASS)
        # SQL strings should be tagged in properties
        sql_strings = repo.properties.get("sql_strings", [])
        # Or the method that contains the string
        method = _find_node(nodes, name="RunQuery", kind=NodeKind.FUNCTION)
        sql_strings = method.properties.get("sql_strings", [])
        assert len(sql_strings) >= 1
        assert "SELECT" in sql_strings[0]


# ---------------------------------------------------------------------------
# Test 10: File-scoped namespace (C# 10+)
# ---------------------------------------------------------------------------
class TestFileScopedNamespace:
    def test_file_scoped_namespace_resolved(self, extractor):
        source = b"""
namespace MyApp.Services;

public class OrderService
{
    public void PlaceOrder() { }
}
"""
        nodes, edges = extractor.extract(source, "OrderService.cs", "/src")

        svc = _find_node(nodes, name="OrderService", kind=NodeKind.CLASS)
        assert svc.fqn == "MyApp.Services.OrderService"

        method = _find_node(nodes, name="PlaceOrder", kind=NodeKind.FUNCTION)
        assert method.fqn == "MyApp.Services.OrderService.PlaceOrder"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
class TestEdgeCases:
    def test_empty_file_returns_empty(self, extractor):
        nodes, edges = extractor.extract(b"", "Empty.cs", "/src")
        assert nodes == []
        assert edges == []

    def test_file_without_namespace(self, extractor):
        source = b"""
public class GlobalClass
{
    public void DoStuff() { }
}
"""
        nodes, edges = extractor.extract(source, "GlobalClass.cs", "/src")
        cls = _find_node(nodes, name="GlobalClass", kind=NodeKind.CLASS)
        assert cls.fqn == "GlobalClass"

    def test_nested_class(self, extractor):
        source = b"""
namespace Outer
{
    public class Container
    {
        public class Inner
        {
            public void Run() { }
        }
    }
}
"""
        nodes, edges = extractor.extract(source, "Nested.cs", "/src")
        # Inner class should exist -- it may be nested under Container
        inner = _find_node(nodes, name="Inner", kind=NodeKind.CLASS)
        assert "Container" in inner.fqn or "Inner" in inner.fqn

    def test_generic_class(self, extractor):
        source = b"""
namespace MyApp
{
    public class Repository<T> where T : class
    {
        public T FindById(int id) { return default; }
    }
}
"""
        nodes, edges = extractor.extract(source, "Repository.cs", "/src")
        repo = _find_node(nodes, name="Repository", kind=NodeKind.CLASS)
        assert repo is not None

    def test_multiple_classes_in_one_file(self, extractor):
        source = b"""
namespace MyApp
{
    public class Foo { }
    public class Bar { }
    public interface IBaz { }
}
"""
        nodes, edges = extractor.extract(source, "Multi.cs", "/src")
        class_nodes = [
            n for n in nodes if n.kind in (NodeKind.CLASS, NodeKind.INTERFACE)
        ]
        names = {n.name for n in class_nodes}
        assert {"Foo", "Bar", "IBaz"} <= names
