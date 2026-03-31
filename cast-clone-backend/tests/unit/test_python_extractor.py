"""Tests for the Python tree-sitter extractor."""

from pathlib import Path

import pytest

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.stages.treesitter.extractors.python import PythonExtractor


@pytest.fixture
def extractor():
    return PythonExtractor()


class TestFQNDerivation:
    """Task 1: FQN derivation and MODULE node creation."""

    def test_module_fqn_from_file_path(self, extractor):
        source = b"def do_work(): pass\n"
        nodes, edges = extractor.extract(source, "/code/mypackage/service.py", "/code")
        module_nodes = [n for n in nodes if n.kind == NodeKind.MODULE]
        assert len(module_nodes) == 1
        assert module_nodes[0].fqn == "mypackage.service"
        assert module_nodes[0].name == "service"
        assert module_nodes[0].language == "python"
        assert module_nodes[0].path == "/code/mypackage/service.py"

    def test_module_fqn_init_file(self, extractor):
        source = b"def init(): pass\n"
        nodes, edges = extractor.extract(source, "/code/mypackage/__init__.py", "/code")
        module_nodes = [n for n in nodes if n.kind == NodeKind.MODULE]
        assert len(module_nodes) == 1
        assert module_nodes[0].fqn == "mypackage"

    def test_module_fqn_top_level_file(self, extractor):
        source = b"def main(): pass\n"
        nodes, edges = extractor.extract(source, "/code/main.py", "/code")
        module_nodes = [n for n in nodes if n.kind == NodeKind.MODULE]
        assert module_nodes[0].fqn == "main"

    def test_empty_file_skips_module(self, extractor):
        """Empty files (e.g. __init__.py) should not create MODULE nodes."""
        source = b""
        nodes, edges = extractor.extract(source, "/code/mypackage/__init__.py", "/code")
        module_nodes = [n for n in nodes if n.kind == NodeKind.MODULE]
        assert len(module_nodes) == 0


class TestClassExtraction:
    """Task 2: Class definitions, inheritance, and decorators."""

    def test_class_with_bases(self, extractor):
        source = b"""\
class Animal:
    pass

class Dog(Animal, Serializable):
    pass
"""
        nodes, edges = extractor.extract(source, "/code/models.py", "/code")

        class_nodes = [n for n in nodes if n.kind == NodeKind.CLASS]
        assert len(class_nodes) == 2
        dog = next(n for n in class_nodes if n.name == "Dog")
        assert dog.fqn == "models.Dog"
        assert dog.language == "python"
        assert dog.line is not None

        inherits = [e for e in edges if e.kind == EdgeKind.INHERITS]
        assert len(inherits) == 2
        targets = {e.target_fqn for e in inherits}
        assert "Animal" in targets
        assert "Serializable" in targets
        for e in inherits:
            assert e.source_fqn == "models.Dog"
            assert e.confidence == Confidence.LOW

    def test_class_with_decorators(self, extractor):
        source = b"""\
@dataclass
@frozen
class Config:
    name: str
"""
        nodes, edges = extractor.extract(source, "/code/config.py", "/code")
        class_nodes = [n for n in nodes if n.kind == NodeKind.CLASS]
        assert len(class_nodes) == 1
        cfg = class_nodes[0]
        assert cfg.fqn == "config.Config"
        assert "dataclass" in cfg.properties["annotations"]
        assert "frozen" in cfg.properties["annotations"]

    def test_class_contains_edge(self, extractor):
        source = b"""\
class Foo:
    pass
"""
        nodes, edges = extractor.extract(source, "/code/foo.py", "/code")
        contains = [
            e
            for e in edges
            if e.kind == EdgeKind.CONTAINS
            and e.source_fqn == "foo"
            and e.target_fqn == "foo.Foo"
        ]
        assert len(contains) == 1


class TestFunctionExtraction:
    """Task 3: Methods and module-level functions."""

    def test_method_with_type_hints(self, extractor):
        source = b"""\
class UserService:
    def create_user(self, name: str, age: int) -> bool:
        pass
"""
        nodes, edges = extractor.extract(source, "/code/svc.py", "/code")
        func_nodes = [n for n in nodes if n.kind == NodeKind.FUNCTION]
        assert len(func_nodes) == 1
        method = func_nodes[0]
        assert method.fqn == "svc.UserService.create_user"
        assert method.name == "create_user"
        assert method.properties.get("is_method") is True
        assert method.properties.get("return_type") == "bool"
        params = method.properties.get("params", [])
        assert len(params) == 2  # self is excluded
        assert params[0]["name"] == "name"
        assert params[0]["type"] == "str"
        assert params[1]["name"] == "age"
        assert params[1]["type"] == "int"

    def test_method_with_decorators(self, extractor):
        source = b"""\
class Router:
    @app.route('/users')
    def get_users(self):
        pass

    @staticmethod
    def helper():
        pass
"""
        nodes, edges = extractor.extract(source, "/code/router.py", "/code")
        func_nodes = [n for n in nodes if n.kind == NodeKind.FUNCTION]
        assert len(func_nodes) == 2

        get_users = next(n for n in func_nodes if n.name == "get_users")
        assert "app.route('/users')" in get_users.properties["annotations"]

        helper = next(n for n in func_nodes if n.name == "helper")
        assert "staticmethod" in helper.properties["annotations"]

    def test_module_level_function(self, extractor):
        source = b"""\
def top_level_func(x: int) -> str:
    return str(x)

class Foo:
    def method(self):
        pass
"""
        nodes, edges = extractor.extract(source, "/code/util.py", "/code")
        func_nodes = [n for n in nodes if n.kind == NodeKind.FUNCTION]
        assert len(func_nodes) == 2

        top = next(n for n in func_nodes if n.name == "top_level_func")
        assert top.fqn == "util.top_level_func"
        # Module-level functions should NOT have is_method
        assert top.properties.get("is_method") is None

        # CONTAINS edge from module to function
        contains = [
            e
            for e in edges
            if e.kind == EdgeKind.CONTAINS
            and e.source_fqn == "util"
            and e.target_fqn == "util.top_level_func"
        ]
        assert len(contains) == 1

    def test_decorated_module_function(self, extractor):
        source = b"""\
@click.command()
def main():
    pass
"""
        nodes, edges = extractor.extract(source, "/code/cli.py", "/code")
        func_nodes = [n for n in nodes if n.kind == NodeKind.FUNCTION]
        assert len(func_nodes) == 1
        assert "click.command()" in func_nodes[0].properties["annotations"]


class TestImportExtraction:
    """Task 4: Import statements -> IMPORTS edges."""

    def test_import_statement(self, extractor):
        source = b"""\
import os
import sys
"""
        nodes, edges = extractor.extract(source, "/code/mod.py", "/code")
        imports = [e for e in edges if e.kind == EdgeKind.IMPORTS]
        targets = {e.target_fqn for e in imports}
        assert "os" in targets
        assert "sys" in targets
        for e in imports:
            assert e.source_fqn == "mod"

    def test_from_import(self, extractor):
        source = b"""\
from os.path import join
from collections import defaultdict, OrderedDict
"""
        nodes, edges = extractor.extract(source, "/code/mod.py", "/code")
        imports = [e for e in edges if e.kind == EdgeKind.IMPORTS]
        targets = {e.target_fqn for e in imports}
        assert "os.path" in targets
        assert "collections" in targets

    def test_aliased_import(self, extractor):
        source = b"""\
import numpy as np
from pandas import DataFrame as DF
"""
        nodes, edges = extractor.extract(source, "/code/mod.py", "/code")
        imports = [e for e in edges if e.kind == EdgeKind.IMPORTS]
        targets = {e.target_fqn for e in imports}
        assert "numpy" in targets
        assert "pandas" in targets


class TestCallExtraction:
    """Task 5: Function/method calls -> CALLS edges."""

    def test_simple_function_call(self, extractor):
        source = b"""\
def caller():
    result = helper()
    return result

def helper():
    pass
"""
        nodes, edges = extractor.extract(source, "/code/mod.py", "/code")
        calls = [e for e in edges if e.kind == EdgeKind.CALLS]
        assert len(calls) >= 1
        helper_call = [e for e in calls if e.target_fqn == "helper"]
        assert len(helper_call) == 1
        assert helper_call[0].source_fqn == "mod.caller"
        assert helper_call[0].confidence == Confidence.LOW

    def test_method_call_on_object(self, extractor):
        source = b"""\
class Service:
    def process(self):
        self.db.execute("query")
        logger.info("done")
"""
        nodes, edges = extractor.extract(source, "/code/svc.py", "/code")
        calls = [e for e in edges if e.kind == EdgeKind.CALLS]
        callee_names = {e.target_fqn for e in calls}
        assert "self.db.execute" in callee_names
        assert "logger.info" in callee_names
        for call in calls:
            if call.target_fqn in ("self.db.execute", "logger.info"):
                assert call.source_fqn == "svc.Service.process"

    def test_call_at_module_level(self, extractor):
        source = b"""\
setup()
"""
        nodes, edges = extractor.extract(source, "/code/mod.py", "/code")
        calls = [e for e in edges if e.kind == EdgeKind.CALLS]
        setup_calls = [e for e in calls if e.target_fqn == "setup"]
        assert len(setup_calls) == 1
        assert setup_calls[0].source_fqn == "mod"


class TestFieldExtraction:
    """Task 6: self.x = ... and class-body fields -> FIELD nodes."""

    def test_init_fields(self, extractor):
        source = b"""\
class User:
    def __init__(self, name: str, age: int):
        self.name = name
        self.age = age
        self._active = True
"""
        nodes, edges = extractor.extract(source, "/code/user.py", "/code")
        field_nodes = [n for n in nodes if n.kind == NodeKind.FIELD]
        field_names = {n.name for n in field_nodes}
        assert "name" in field_names
        assert "age" in field_names
        assert "_active" in field_names

        for fn in field_nodes:
            assert fn.fqn.startswith("user.User.")
            # CONTAINS edge from class to field
            contains = [
                e
                for e in edges
                if e.kind == EdgeKind.CONTAINS
                and e.target_fqn == fn.fqn
                and e.source_fqn == "user.User"
            ]
            assert len(contains) == 1

    def test_class_body_fields(self, extractor):
        source = b"""\
class Config:
    DEBUG = False
    MAX_RETRIES = 3
"""
        nodes, edges = extractor.extract(source, "/code/cfg.py", "/code")
        field_nodes = [n for n in nodes if n.kind == NodeKind.FIELD]
        field_names = {n.name for n in field_nodes}
        assert "DEBUG" in field_names
        assert "MAX_RETRIES" in field_names

    def test_no_duplicate_fields(self, extractor):
        source = b"""\
class Foo:
    def __init__(self):
        self.x = 1
        self.x = 2
"""
        nodes, edges = extractor.extract(source, "/code/foo.py", "/code")
        field_nodes = [n for n in nodes if n.kind == NodeKind.FIELD]
        assert len(field_nodes) == 1
        assert field_nodes[0].name == "x"


class TestSQLStringDetection:
    """Task 7: SQL-like string literals tagged on enclosing function."""

    def test_sql_string_detected(self, extractor):
        source = b"""\
class Repository:
    def find_users(self):
        query = "SELECT id, name FROM users WHERE active = 1"
        return self.execute(query)
"""
        nodes, edges = extractor.extract(source, "/code/repo.py", "/code")
        func = next(
            n for n in nodes if n.kind == NodeKind.FUNCTION and n.name == "find_users"
        )
        sql_strings = func.properties.get("sql_strings", [])
        assert len(sql_strings) >= 1
        assert any("SELECT" in s["text"] and "FROM" in s["text"] for s in sql_strings)

    def test_non_sql_string_not_tagged(self, extractor):
        source = b"""\
def greet():
    return "Hello, world!"
"""
        nodes, edges = extractor.extract(source, "/code/greet.py", "/code")
        func = next(
            n for n in nodes if n.kind == NodeKind.FUNCTION and n.name == "greet"
        )
        assert func.properties.get("sql_strings") is None

    def test_triple_quoted_sql(self, extractor):
        source = b'''\
def get_report():
    sql = """
        SELECT u.name, COUNT(o.id)
        FROM users u
        JOIN orders o ON o.user_id = u.id
        GROUP BY u.name
    """
    return execute(sql)
'''
        nodes, edges = extractor.extract(source, "/code/report.py", "/code")
        func = next(
            n for n in nodes if n.kind == NodeKind.FUNCTION and n.name == "get_report"
        )
        sql_strings = func.properties.get("sql_strings", [])
        assert len(sql_strings) >= 1


class TestFullIntegration:
    """Task 8: End-to-end integration test with realistic fixture."""

    @pytest.fixture
    def fixture_source(self):
        fixture_path = (
            Path(__file__).parent.parent
            / "fixtures"
            / "python-sample"
            / "mypackage"
            / "service.py"
        )
        return fixture_path.read_bytes(), str(fixture_path)

    def test_full_extraction(self, extractor, fixture_source):
        source, file_path = fixture_source
        root_path = str(Path(__file__).parent.parent / "fixtures" / "python-sample")
        nodes, edges = extractor.extract(source, file_path, root_path)

        # MODULE
        module_nodes = [n for n in nodes if n.kind == NodeKind.MODULE]
        assert len(module_nodes) == 1
        assert module_nodes[0].fqn == "mypackage.service"

        # CLASSES
        class_nodes = [n for n in nodes if n.kind == NodeKind.CLASS]
        class_names = {n.name for n in class_nodes}
        assert "BaseService" in class_names
        assert "UserService" in class_names

        # UserService inherits BaseService
        inherits = [
            e
            for e in edges
            if e.kind == EdgeKind.INHERITS
            and e.source_fqn == "mypackage.service.UserService"
        ]
        assert any(e.target_fqn == "BaseService" for e in inherits)

        # FUNCTIONS (methods + module-level)
        func_nodes = [n for n in nodes if n.kind == NodeKind.FUNCTION]
        func_names = {n.name for n in func_nodes}
        assert "find_by_email" in func_names
        assert "count_active" in func_names
        assert "validate_email" in func_names
        assert "create_service" in func_names
        assert "__init__" in func_names

        # Method type hints
        find_by = next(n for n in func_nodes if n.name == "find_by_email")
        assert find_by.properties.get("return_type") is not None
        params = find_by.properties.get("params", [])
        assert any(p.get("name") == "email" for p in params)

        # Decorator on validate_email
        validate = next(n for n in func_nodes if n.name == "validate_email")
        assert "staticmethod" in validate.properties.get("annotations", [])

        # FIELDS from __init__
        field_nodes = [n for n in nodes if n.kind == NodeKind.FIELD]
        field_names = {n.name for n in field_nodes}
        assert "cache" in field_names
        assert "_initialized" in field_names

        # Class-body field
        assert "DEFAULT_PAGE_SIZE" in field_names

        # IMPORTS
        import_edges = [e for e in edges if e.kind == EdgeKind.IMPORTS]
        import_targets = {e.target_fqn for e in import_edges}
        assert "logging" in import_targets
        assert "typing" in import_targets
        assert "sqlalchemy.orm" in import_targets

        # CALLS edges exist
        calls = [e for e in edges if e.kind == EdgeKind.CALLS]
        assert len(calls) > 0
        # find_by_email calls self.db.execute
        db_calls = [
            e
            for e in calls
            if "find_by_email" in e.source_fqn and "execute" in e.target_fqn
        ]
        assert len(db_calls) >= 1

        # SQL strings tagged
        sql_funcs = [n for n in func_nodes if n.properties.get("sql_strings")]
        assert len(sql_funcs) >= 1

        # Module-level function CONTAINS edge
        factory_contains = [
            e
            for e in edges
            if e.kind == EdgeKind.CONTAINS
            and e.target_fqn == "mypackage.service.create_service"
        ]
        assert len(factory_contains) == 1
        assert factory_contains[0].source_fqn == "mypackage.service"

    def test_node_and_edge_counts_reasonable(self, extractor, fixture_source):
        source, file_path = fixture_source
        root_path = str(Path(__file__).parent.parent / "fixtures" / "python-sample")
        nodes, edges = extractor.extract(source, file_path, root_path)

        # Sanity: we should have a reasonable number of items
        assert len(nodes) >= 10  # 1 module + 2 classes + 5+ functions + fields
        assert len(edges) >= 10  # contains + inherits + imports + calls
