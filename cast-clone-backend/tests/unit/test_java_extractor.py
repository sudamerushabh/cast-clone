# tests/unit/test_java_extractor.py
import pytest

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.stages.treesitter.extractors.java import JavaExtractor


@pytest.fixture
def extractor():
    return JavaExtractor()


def _find_node(nodes, fqn):
    """Helper: find a node by FQN."""
    for n in nodes:
        if n.fqn == fqn:
            return n
    return None


def _find_nodes(nodes, kind):
    """Helper: find all nodes of a given kind."""
    return [n for n in nodes if n.kind == kind]


def _find_edge(edges, source_fqn, target_fqn, kind):
    """Helper: find an edge by source, target, and kind."""
    for e in edges:
        if e.source_fqn == source_fqn and e.target_fqn == target_fqn and e.kind == kind:
            return e
    return None


def _find_edges(edges, kind):
    """Helper: find all edges of a given kind."""
    return [e for e in edges if e.kind == kind]


# ──────────────────────────────────────────────
# Test 1: Basic class
# ──────────────────────────────────────────────
class TestBasicClass:
    def test_public_class_node(self, extractor):
        source = b"""\
package com.example.service;

public class UserService {
}
"""
        nodes, edges = extractor.extract(source, "UserService.java", "/project")

        node = _find_node(nodes, "com.example.service.UserService")
        assert node is not None
        assert node.name == "UserService"
        assert node.kind == NodeKind.CLASS
        assert node.language == "java"
        assert node.path == "UserService.java"
        assert node.line is not None
        assert node.properties.get("visibility") == "public"

    def test_default_visibility_class(self, extractor):
        source = b"""\
package com.example;

class Internal {
}
"""
        nodes, edges = extractor.extract(source, "Internal.java", "/project")
        node = _find_node(nodes, "com.example.Internal")
        assert node is not None
        assert node.properties.get("visibility") == "default"

    def test_no_package_class(self, extractor):
        source = b"""\
public class NoPackage {
}
"""
        nodes, edges = extractor.extract(source, "NoPackage.java", "/project")
        node = _find_node(nodes, "NoPackage")
        assert node is not None


# ──────────────────────────────────────────────
# Test 2: Inheritance and interfaces
# ──────────────────────────────────────────────
class TestInheritance:
    def test_extends_and_implements(self, extractor):
        source = b"""\
package com.example;

public class Dog extends Animal implements Runnable, Serializable {
}
"""
        nodes, edges = extractor.extract(source, "Dog.java", "/project")

        node = _find_node(nodes, "com.example.Dog")
        assert node is not None
        assert node.kind == NodeKind.CLASS

        inherits = _find_edge(edges, "com.example.Dog", "Animal", EdgeKind.INHERITS)
        assert inherits is not None

        impl_runnable = _find_edge(
            edges,
            "com.example.Dog",
            "Runnable",
            EdgeKind.IMPLEMENTS,
        )
        assert impl_runnable is not None

        impl_serializable = _find_edge(
            edges,
            "com.example.Dog",
            "Serializable",
            EdgeKind.IMPLEMENTS,
        )
        assert impl_serializable is not None

    def test_interface_extends(self, extractor):
        source = b"""\
package com.example;

public interface UserRepository extends JpaRepository, CustomRepo {
}
"""
        nodes, edges = extractor.extract(source, "UserRepository.java", "/project")

        node = _find_node(nodes, "com.example.UserRepository")
        assert node is not None
        assert node.kind == NodeKind.INTERFACE

        inherits_edges = [
            e
            for e in edges
            if e.source_fqn == "com.example.UserRepository"
            and e.kind == EdgeKind.INHERITS
        ]
        assert len(inherits_edges) == 2

    def test_interface_extends_generic(self, extractor):
        """Interface extending a generic type should produce an INHERITS edge."""
        source = b"""
package com.example;
public interface AccountRepo extends JpaRepository<Account, Long> {}
"""
        nodes, edges = extractor.extract(source, "AccountRepo.java", "/project")
        inherits_edges = [
            e
            for e in edges
            if "AccountRepo" in e.source_fqn and e.kind == EdgeKind.INHERITS
        ]
        assert len(inherits_edges) == 1
        assert "JpaRepository" in inherits_edges[0].target_fqn


# ──────────────────────────────────────────────
# Test 3: Methods
# ──────────────────────────────────────────────
class TestMethods:
    def test_method_extraction(self, extractor):
        source = b"""\
package com.example;

public class UserService {
    public User findById(Long id) {
        return null;
    }

    private void validate(String input, int count) {
    }
}
"""
        nodes, edges = extractor.extract(source, "UserService.java", "/project")

        find_method = _find_node(nodes, "com.example.UserService.findById")
        assert find_method is not None
        assert find_method.kind == NodeKind.FUNCTION
        assert find_method.properties.get("return_type") == "User"
        assert find_method.properties.get("params") == ["Long id"]
        assert find_method.properties.get("visibility") == "public"

        validate_method = _find_node(nodes, "com.example.UserService.validate")
        assert validate_method is not None
        assert validate_method.properties.get("params") == ["String input", "int count"]
        assert validate_method.properties.get("visibility") == "private"

        # CONTAINS edges
        contains_find = _find_edge(
            edges,
            "com.example.UserService",
            "com.example.UserService.findById",
            EdgeKind.CONTAINS,
        )
        assert contains_find is not None

    def test_method_with_annotations(self, extractor):
        source = b"""\
package com.example;

public class Controller {
    @GetMapping("/users")
    @ResponseBody
    public List<User> getUsers() {
        return null;
    }
}
"""
        nodes, edges = extractor.extract(source, "Controller.java", "/project")

        method = _find_node(nodes, "com.example.Controller.getUsers")
        assert method is not None
        annotations = method.properties.get("annotations", [])
        assert "GetMapping" in annotations
        assert "ResponseBody" in annotations


# ──────────────────────────────────────────────
# Test 4: Fields
# ──────────────────────────────────────────────
class TestFields:
    def test_field_extraction(self, extractor):
        source = b"""\
package com.example;

public class UserService {
    @Autowired
    private UserRepository repo;

    public static final String NAME = "test";
}
"""
        nodes, edges = extractor.extract(source, "UserService.java", "/project")

        repo_field = _find_node(nodes, "com.example.UserService.repo")
        assert repo_field is not None
        assert repo_field.kind == NodeKind.FIELD
        assert repo_field.properties.get("type") == "UserRepository"
        assert repo_field.properties.get("visibility") == "private"
        assert "Autowired" in repo_field.properties.get("annotations", [])

        name_field = _find_node(nodes, "com.example.UserService.NAME")
        assert name_field is not None
        assert name_field.properties.get("is_static") is True
        assert name_field.properties.get("is_final") is True

        # CONTAINS edges
        contains = _find_edge(
            edges,
            "com.example.UserService",
            "com.example.UserService.repo",
            EdgeKind.CONTAINS,
        )
        assert contains is not None


# ──────────────────────────────────────────────
# Test 5: Method calls
# ──────────────────────────────────────────────
class TestMethodCalls:
    def test_method_invocation(self, extractor):
        source = b"""\
package com.example;

public class UserService {
    private UserRepository repo;

    public void createUser(User user) {
        repo.save(user);
        validate(user);
    }

    private void validate(User user) {
    }
}
"""
        nodes, edges = extractor.extract(source, "UserService.java", "/project")

        call_edges = _find_edges(edges, EdgeKind.CALLS)

        # repo.save(user) -> resolved via field type + same-package qualification
        repo_save = [e for e in call_edges if "save" in e.target_fqn]
        assert len(repo_save) >= 1
        assert repo_save[0].source_fqn == "com.example.UserService.createUser"
        assert repo_save[0].target_fqn == "com.example.UserRepository.save"
        assert repo_save[0].confidence == Confidence.MEDIUM

        # validate(user) -> no receiver, resolves to same class
        validate_call = [e for e in call_edges if "validate" in e.target_fqn]
        assert len(validate_call) >= 1
        assert validate_call[0].target_fqn == "com.example.UserService.validate"
        assert validate_call[0].confidence == Confidence.MEDIUM

    def test_object_creation(self, extractor):
        source = b"""\
package com.example;

public class Factory {
    public User create() {
        return new User("test");
    }
}
"""
        nodes, edges = extractor.extract(source, "Factory.java", "/project")

        call_edges = _find_edges(edges, EdgeKind.CALLS)
        init_call = [e for e in call_edges if "User.<init>" in e.target_fqn]
        assert len(init_call) >= 1
        assert init_call[0].source_fqn == "com.example.Factory.create"
        assert init_call[0].confidence == Confidence.LOW


# ──────────────────────────────────────────────
# Test 6: Imports
# ──────────────────────────────────────────────
class TestImports:
    def test_import_resolution_map(self, extractor):
        source = b"""\
package com.example;

import com.example.model.User;
import com.example.repo.*;
import java.util.List;

public class UserService {
}
"""
        nodes, edges = extractor.extract(source, "UserService.java", "/project")

        # Imports should be stored on the extractor result or used for FQN resolution.
        # For now, verify IMPORTS edges are created.
        import_edges = _find_edges(edges, EdgeKind.IMPORTS)
        import_targets = {e.target_fqn for e in import_edges}
        assert "com.example.model.User" in import_targets
        assert "com.example.repo.*" in import_targets
        assert "java.util.List" in import_targets


# ──────────────────────────────────────────────
# Test 7: Annotations on class
# ──────────────────────────────────────────────
class TestAnnotations:
    def test_class_annotations(self, extractor):
        source = b"""\
package com.example;

@Service
@Transactional
public class UserService {
}
"""
        nodes, edges = extractor.extract(source, "UserService.java", "/project")

        node = _find_node(nodes, "com.example.UserService")
        assert node is not None
        annotations = node.properties.get("annotations", [])
        assert "Service" in annotations
        assert "Transactional" in annotations


# ──────────────────────────────────────────────
# Test 8: Constructor
# ──────────────────────────────────────────────
class TestConstructor:
    def test_constructor_extraction(self, extractor):
        source = b"""\
package com.example;

public class UserService {
    private final UserRepository repo;

    public UserService(UserRepository repo) {
        this.repo = repo;
    }
}
"""
        nodes, edges = extractor.extract(source, "UserService.java", "/project")

        ctor = _find_node(nodes, "com.example.UserService.<init>")
        assert ctor is not None
        assert ctor.kind == NodeKind.FUNCTION
        assert ctor.properties.get("is_constructor") is True
        assert ctor.properties.get("params") == ["UserRepository repo"]

        contains = _find_edge(
            edges,
            "com.example.UserService",
            "com.example.UserService.<init>",
            EdgeKind.CONTAINS,
        )
        assert contains is not None


# ──────────────────────────────────────────────
# Test 9: Full file integration
# ──────────────────────────────────────────────
class TestFullFile:
    FULL_SOURCE = b"""\
package com.example.service;

import com.example.model.User;
import com.example.repository.UserRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@Transactional
public class UserService {

    @Autowired
    private UserRepository userRepo;

    private static final String TABLE = "users";

    public UserService(UserRepository userRepo) {
        this.userRepo = userRepo;
    }

    public User findById(Long id) {
        return userRepo.findById(id);
    }

    public User createUser(String name) {
        User user = new User(name);
        userRepo.save(user);
        return user;
    }

    public void deleteAll() {
        String sql = "DELETE FROM users WHERE active = false";
        userRepo.executeSql(sql);
    }
}
"""

    def test_all_class_nodes(self, extractor):
        nodes, edges = extractor.extract(
            self.FULL_SOURCE, "UserService.java", "/project"
        )

        class_node = _find_node(nodes, "com.example.service.UserService")
        assert class_node is not None
        assert class_node.kind == NodeKind.CLASS
        assert "Service" in class_node.properties.get("annotations", [])
        assert "Transactional" in class_node.properties.get("annotations", [])

    def test_all_method_nodes(self, extractor):
        nodes, edges = extractor.extract(
            self.FULL_SOURCE, "UserService.java", "/project"
        )

        method_names = {n.fqn for n in nodes if n.kind == NodeKind.FUNCTION}
        assert "com.example.service.UserService.<init>" in method_names
        assert "com.example.service.UserService.findById" in method_names
        assert "com.example.service.UserService.createUser" in method_names
        assert "com.example.service.UserService.deleteAll" in method_names

    def test_all_field_nodes(self, extractor):
        nodes, edges = extractor.extract(
            self.FULL_SOURCE, "UserService.java", "/project"
        )

        field_names = {n.fqn for n in nodes if n.kind == NodeKind.FIELD}
        assert "com.example.service.UserService.userRepo" in field_names
        assert "com.example.service.UserService.TABLE" in field_names

    def test_all_contains_edges(self, extractor):
        nodes, edges = extractor.extract(
            self.FULL_SOURCE, "UserService.java", "/project"
        )

        contains_edges = _find_edges(edges, EdgeKind.CONTAINS)
        contained_targets = {e.target_fqn for e in contains_edges}
        assert "com.example.service.UserService.<init>" in contained_targets
        assert "com.example.service.UserService.findById" in contained_targets
        assert "com.example.service.UserService.userRepo" in contained_targets

    def test_all_calls_edges(self, extractor):
        nodes, edges = extractor.extract(
            self.FULL_SOURCE, "UserService.java", "/project"
        )

        call_edges = _find_edges(edges, EdgeKind.CALLS)
        # createUser calls new User() and userRepo.save()
        create_calls = [
            e
            for e in call_edges
            if e.source_fqn == "com.example.service.UserService.createUser"
        ]
        call_targets = {e.target_fqn for e in create_calls}
        assert any("User.<init>" in t for t in call_targets)
        assert any("save" in t for t in call_targets)

    def test_imports(self, extractor):
        nodes, edges = extractor.extract(
            self.FULL_SOURCE, "UserService.java", "/project"
        )

        import_edges = _find_edges(edges, EdgeKind.IMPORTS)
        import_targets = {e.target_fqn for e in import_edges}
        assert "com.example.model.User" in import_targets
        assert "com.example.repository.UserRepository" in import_targets

    def test_sql_tagged_strings(self, extractor):
        nodes, edges = extractor.extract(
            self.FULL_SOURCE, "UserService.java", "/project"
        )

        delete_method = _find_node(nodes, "com.example.service.UserService.deleteAll")
        assert delete_method is not None
        tagged = delete_method.properties.get("tagged_strings", [])
        assert any("DELETE" in s for s in tagged)

    def test_node_counts(self, extractor):
        nodes, edges = extractor.extract(
            self.FULL_SOURCE, "UserService.java", "/project"
        )

        class_count = len(_find_nodes(nodes, NodeKind.CLASS))
        method_count = len(_find_nodes(nodes, NodeKind.FUNCTION))
        field_count = len(_find_nodes(nodes, NodeKind.FIELD))

        assert class_count == 1
        assert method_count == 4  # constructor + 3 methods
        assert field_count == 2  # userRepo + TABLE


# ──────────────────────────────────────────────
# Test 10: Method call resolution
# ──────────────────────────────────────────────
class TestMethodCallResolution:
    def test_field_receiver_resolves_via_import(self, extractor):
        source = b"""\
package com.example;

import com.example.repo.UserRepository;

public class UserService {
    private UserRepository userRepo;

    public void doWork() {
        userRepo.save();
    }
}
"""
        nodes, edges = extractor.extract(source, "UserService.java", "/project")
        call_edges = _find_edges(edges, EdgeKind.CALLS)
        save_calls = [e for e in call_edges if "save" in e.target_fqn]
        assert len(save_calls) == 1
        assert save_calls[0].target_fqn == "com.example.repo.UserRepository.save"
        assert save_calls[0].confidence == Confidence.MEDIUM

    def test_this_field_receiver_resolves(self, extractor):
        source = b"""\
package com.example;

import com.example.repo.UserRepository;

public class UserService {
    private UserRepository repo;

    public void doWork() {
        this.repo.findAll();
    }
}
"""
        nodes, edges = extractor.extract(source, "UserService.java", "/project")
        call_edges = _find_edges(edges, EdgeKind.CALLS)
        find_calls = [e for e in call_edges if "findAll" in e.target_fqn]
        assert len(find_calls) == 1
        assert find_calls[0].target_fqn == "com.example.repo.UserRepository.findAll"
        assert find_calls[0].confidence == Confidence.MEDIUM

    def test_local_var_receiver_resolves(self, extractor):
        source = b"""\
package com.example;

import com.example.model.User;

public class UserService {
    public void doWork() {
        User user = new User();
        user.setName();
    }
}
"""
        nodes, edges = extractor.extract(source, "UserService.java", "/project")
        call_edges = _find_edges(edges, EdgeKind.CALLS)
        set_calls = [e for e in call_edges if "setName" in e.target_fqn]
        assert len(set_calls) == 1
        assert set_calls[0].target_fqn == "com.example.model.User.setName"
        assert set_calls[0].confidence == Confidence.MEDIUM

    def test_no_receiver_resolves_to_same_class(self, extractor):
        source = b"""\
package com.example;

public class UserService {
    public void doWork() {
        validate();
    }

    private void validate() {
    }
}
"""
        nodes, edges = extractor.extract(source, "UserService.java", "/project")
        call_edges = _find_edges(edges, EdgeKind.CALLS)
        validate_calls = [e for e in call_edges if "validate" in e.target_fqn]
        assert len(validate_calls) == 1
        assert validate_calls[0].target_fqn == "com.example.UserService.validate"
        assert validate_calls[0].confidence == Confidence.MEDIUM

    def test_unresolvable_receiver_stays_low(self, extractor):
        source = b"""\
package com.example;

public class UserService {
    public void doWork() {
        unknownThing.doSomething();
    }
}
"""
        nodes, edges = extractor.extract(source, "UserService.java", "/project")
        call_edges = _find_edges(edges, EdgeKind.CALLS)
        unknown_calls = [e for e in call_edges if "doSomething" in e.target_fqn]
        assert len(unknown_calls) == 1
        assert unknown_calls[0].target_fqn == "unknownThing.doSomething"
        assert unknown_calls[0].confidence == Confidence.LOW

    def test_static_call_on_class_name(self, extractor):
        source = b"""\
package com.example;

import java.util.Collections;

public class UserService {
    public void doWork() {
        Collections.emptyList();
    }
}
"""
        nodes, edges = extractor.extract(source, "UserService.java", "/project")
        call_edges = _find_edges(edges, EdgeKind.CALLS)
        static_calls = [e for e in call_edges if "emptyList" in e.target_fqn]
        assert len(static_calls) == 1
        assert static_calls[0].target_fqn == "java.util.Collections.emptyList"
        assert static_calls[0].confidence == Confidence.MEDIUM


# ──────────────────────────────────────────────
# Nested-class FQN collision regression (CHAN-76)
# ──────────────────────────────────────────────
class TestNestedClassFqn:
    """Ensure nested types carry the outer class name in their FQN so that
    a ``com.foo.Outer.Inner`` never collides with a top-level
    ``com.foo.Inner`` declared elsewhere."""

    def test_nested_class_fqn_includes_outer(self, extractor):
        source = b"""\
package com.foo;

public class Outer {
    public static class Inner {
    }
}
"""
        nodes, _edges = extractor.extract(source, "Outer.java", "/project")

        outer = _find_node(nodes, "com.foo.Outer")
        assert outer is not None
        assert outer.kind == NodeKind.CLASS

        inner = _find_node(nodes, "com.foo.Outer.Inner")
        assert inner is not None, (
            "Nested class FQN must include the outer class name, "
            "got FQNs: " + ", ".join(n.fqn for n in nodes)
        )
        assert inner.name == "Inner"
        assert inner.kind == NodeKind.CLASS

        # Must NOT be written as a top-level com.foo.Inner
        assert _find_node(nodes, "com.foo.Inner") is None

    def test_deeply_nested_class_fqn(self, extractor):
        source = b"""\
package com.foo;

public class Outer {
    public static class Mid {
        public static class Inner {
        }
    }
}
"""
        nodes, _edges = extractor.extract(source, "Outer.java", "/project")

        inner = _find_node(nodes, "com.foo.Outer.Mid.Inner")
        assert inner is not None, (
            "Deeply nested class FQN must include all outer class names, "
            "got FQNs: " + ", ".join(n.fqn for n in nodes)
        )
        assert inner.kind == NodeKind.CLASS

        # Neither the shallower collision path nor the bare form should exist
        assert _find_node(nodes, "com.foo.Mid.Inner") is None
        assert _find_node(nodes, "com.foo.Inner") is None

    def test_method_in_nested_class_fqn(self, extractor):
        source = b"""\
package com.foo;

public class Outer {
    public static class Inner {
        public void doIt() {
        }
    }
}
"""
        nodes, edges = extractor.extract(source, "Outer.java", "/project")

        method = _find_node(nodes, "com.foo.Outer.Inner.doIt")
        assert method is not None, (
            "Method in nested class must carry the outer class in its FQN, "
            "got FQNs: " + ", ".join(n.fqn for n in nodes)
        )
        assert method.kind == NodeKind.FUNCTION

        # CONTAINS edge from the nested class to the method
        contains = _find_edge(
            edges,
            "com.foo.Outer.Inner",
            "com.foo.Outer.Inner.doIt",
            EdgeKind.CONTAINS,
        )
        assert contains is not None

        # Must not leak a collision FQN
        assert _find_node(nodes, "com.foo.Inner.doIt") is None

    def test_top_level_classes_unchanged(self, extractor):
        """Sibling classes at the package level must not gain a duplicated segment."""
        source = b"""\
package com.foo;

public class First {
}

class Second {
}
"""
        nodes, _edges = extractor.extract(source, "Siblings.java", "/project")

        first = _find_node(nodes, "com.foo.First")
        assert first is not None
        second = _find_node(nodes, "com.foo.Second")
        assert second is not None

        # Guard against regressions where the walker double-counted the node itself.
        for bogus in (
            "com.foo.First.First",
            "com.foo.Second.Second",
            "com.foo.First.Second",
        ):
            assert _find_node(nodes, bogus) is None, (
                f"Top-level classes must not produce nested-looking FQN {bogus}"
            )

    def test_two_files_with_same_inner_name_no_collision(self, extractor):
        """``A.Inner`` and ``B.Inner`` in the same package must get distinct FQNs."""
        source_a = b"""\
package com.foo;

public class A {
    public static class Inner {
        public void ping() {}
    }
}
"""
        source_b = b"""\
package com.foo;

public class B {
    public static class Inner {
        public void pong() {}
    }
}
"""
        nodes_a, _ = extractor.extract(source_a, "A.java", "/project")
        nodes_b, _ = extractor.extract(source_b, "B.java", "/project")

        a_inner = _find_node(nodes_a, "com.foo.A.Inner")
        b_inner = _find_node(nodes_b, "com.foo.B.Inner")
        assert a_inner is not None
        assert b_inner is not None
        assert a_inner.fqn != b_inner.fqn

        # And neither file should emit the collision-prone ``com.foo.Inner``.
        assert _find_node(nodes_a, "com.foo.Inner") is None
        assert _find_node(nodes_b, "com.foo.Inner") is None

        # Methods must also be disambiguated by their outer class.
        assert _find_node(nodes_a, "com.foo.A.Inner.ping") is not None
        assert _find_node(nodes_b, "com.foo.B.Inner.pong") is not None
        assert _find_node(nodes_a, "com.foo.Inner.ping") is None
        assert _find_node(nodes_b, "com.foo.Inner.pong") is None


# ──────────────────────────────────────────────
# Records, annotation types, local classes (CHAN-76)
# ──────────────────────────────────────────────
class TestNestedDeclarationFQNs:
    def test_nested_record_fqn_includes_outer(self, extractor):
        """A record declared inside a class is FQN-qualified by its outer class."""
        source = b"""\
package com.foo;

public class Outer {
    public record Point(int x, int y) {}
}
"""
        nodes, _ = extractor.extract(source, "Outer.java", "/project")
        # The record node itself is a record_declaration, not a class_declaration,
        # so it isn't emitted as a CLASS node, but any nested class inside it
        # would include Outer.Point in its FQN. Verify the nesting logic via a
        # nested class inside the record.
        source_nested = b"""\
package com.foo;

public class Outer {
    public record Point(int x, int y) {
        public static class Helper {}
    }
}
"""
        nodes, _ = extractor.extract(source_nested, "Outer.java", "/project")
        helper = _find_node(nodes, "com.foo.Outer.Point.Helper")
        assert helper is not None, (
            "Nested class inside record should carry Outer.Point in its FQN; "
            f"got FQNs: {[n.fqn for n in nodes if n.kind == NodeKind.CLASS]}"
        )
        # The collision-prone flat FQN must NOT exist.
        assert _find_node(nodes, "com.foo.Helper") is None

    def test_nested_annotation_type_fqn(self, extractor):
        """A @interface declared inside a class qualifies nested types with it."""
        source = b"""\
package com.foo;

public class Outer {
    public @interface MyAnn {
        class Inner {}
    }
}
"""
        nodes, _ = extractor.extract(source, "Outer.java", "/project")
        inner = _find_node(nodes, "com.foo.Outer.MyAnn.Inner")
        class_fqns = [n.fqn for n in nodes if n.kind == NodeKind.CLASS]
        assert inner is not None, (
            "Class inside annotation_type_declaration should include outer "
            f"annotation in FQN; got: {class_fqns}"
        )
        assert _find_node(nodes, "com.foo.Inner") is None

    def test_local_class_in_method_fqn(self, extractor):
        """A class declared inside a method is FQN-qualified with {method}$local."""
        source = b"""\
package com.foo;

public class Outer {
    public void doWork() {
        class Helper {
            void help() {}
        }
    }
}
"""
        nodes, _ = extractor.extract(source, "Outer.java", "/project")
        helper = _find_node(nodes, "com.foo.Outer.doWork$local.Helper")
        assert helper is not None, (
            "Local class should carry {method}$local segment; got: "
            f"{[n.fqn for n in nodes if n.kind == NodeKind.CLASS]}"
        )
        # Without the disambiguator, this collides with a top-level Helper.
        assert _find_node(nodes, "com.foo.Outer.Helper") is None
        # Method inside the local class should also be qualified.
        assert (
            _find_node(nodes, "com.foo.Outer.doWork$local.Helper.help") is not None
        )

    def test_two_methods_local_class_same_name_distinct(self, extractor):
        """Two methods each declaring `class Helper {}` produce distinct FQNs."""
        source = b"""\
package com.foo;

public class Outer {
    public void first() {
        class Helper {
            void a() {}
        }
    }

    public void second() {
        class Helper {
            void b() {}
        }
    }
}
"""
        nodes, _ = extractor.extract(source, "Outer.java", "/project")
        first_helper = _find_node(nodes, "com.foo.Outer.first$local.Helper")
        second_helper = _find_node(nodes, "com.foo.Outer.second$local.Helper")
        assert first_helper is not None
        assert second_helper is not None
        assert first_helper.fqn != second_helper.fqn
        # Methods inside each local class are also distinct.
        assert _find_node(nodes, "com.foo.Outer.first$local.Helper.a") is not None
        assert _find_node(nodes, "com.foo.Outer.second$local.Helper.b") is not None
