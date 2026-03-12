"""Tests for the TypeScript/JavaScript tree-sitter extractor.

Covers: classes, interfaces, functions (named + arrow), methods, imports,
decorators, JSX elements, exports, method calls, and a full-file integration test.
"""

import pytest

from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode
from app.stages.treesitter.extractors.typescript import TypeScriptExtractor


@pytest.fixture
def extractor() -> TypeScriptExtractor:
    return TypeScriptExtractor()


def _find_node(
    nodes: list[GraphNode], *, name: str | None = None, kind: NodeKind | None = None
) -> GraphNode | None:
    for n in nodes:
        if name is not None and n.name != name:
            continue
        if kind is not None and n.kind != kind:
            continue
        return n
    return None


def _find_edge(
    edges: list[GraphEdge],
    *,
    kind: EdgeKind | None = None,
    source_contains: str | None = None,
    target_contains: str | None = None,
) -> GraphEdge | None:
    for e in edges:
        if kind is not None and e.kind != kind:
            continue
        if source_contains is not None and source_contains not in e.source_fqn:
            continue
        if target_contains is not None and target_contains not in e.target_fqn:
            continue
        return e
    return None


def _find_edges(
    edges: list[GraphEdge],
    *,
    kind: EdgeKind | None = None,
    source_contains: str | None = None,
    target_contains: str | None = None,
) -> list[GraphEdge]:
    result = []
    for e in edges:
        if kind is not None and e.kind != kind:
            continue
        if source_contains is not None and source_contains not in e.source_fqn:
            continue
        if target_contains is not None and target_contains not in e.target_fqn:
            continue
        result.append(e)
    return result


# ---------------------------------------------------------------------------
# Test 1: Class with extends
# ---------------------------------------------------------------------------
class TestClassWithExtends:
    SOURCE = b"""\
class Animal {
    name: string;

    constructor(name: string) {
        this.name = name;
    }

    speak(): string {
        return this.name;
    }
}

class Dog extends Animal {
    breed: string;

    bark(): void {
        console.log("Woof!");
    }
}
"""

    def test_class_nodes_created(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/animals.ts", "/project")
        animal = _find_node(nodes, name="Animal", kind=NodeKind.CLASS)
        dog = _find_node(nodes, name="Dog", kind=NodeKind.CLASS)
        assert animal is not None
        assert dog is not None
        assert animal.language == "typescript"
        assert animal.path == "src/animals.ts"
        assert animal.fqn == "src/animals.Animal"
        assert dog.fqn == "src/animals.Dog"

    def test_inherits_edge(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/animals.ts", "/project")
        inherits = _find_edge(
            edges,
            kind=EdgeKind.INHERITS,
            source_contains="Dog",
            target_contains="Animal",
        )
        assert inherits is not None

    def test_methods_extracted(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/animals.ts", "/project")
        speak = _find_node(nodes, name="speak", kind=NodeKind.FUNCTION)
        bark = _find_node(nodes, name="bark", kind=NodeKind.FUNCTION)
        assert speak is not None
        assert bark is not None
        assert speak.fqn == "src/animals.Animal.speak"
        assert bark.fqn == "src/animals.Dog.bark"

    def test_contains_edges_for_methods(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/animals.ts", "/project")
        contains = _find_edge(
            edges,
            kind=EdgeKind.CONTAINS,
            source_contains="Animal",
            target_contains="speak",
        )
        assert contains is not None


# ---------------------------------------------------------------------------
# Test 2: Function declarations (named + arrow)
# ---------------------------------------------------------------------------
class TestFunctionDeclarations:
    SOURCE = b"""\
function greet(name: string): string {
    return `Hello, ${name}!`;
}

const add = (a: number, b: number): number => {
    return a + b;
};

export function multiply(x: number, y: number): number {
    return x * y;
}

export const divide = (x: number, y: number): number => x / y;
"""

    def test_named_function(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/utils.ts", "/project")
        greet = _find_node(nodes, name="greet", kind=NodeKind.FUNCTION)
        assert greet is not None
        assert greet.fqn == "src/utils.greet"

    def test_arrow_function(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/utils.ts", "/project")
        add = _find_node(nodes, name="add", kind=NodeKind.FUNCTION)
        assert add is not None
        assert add.fqn == "src/utils.add"

    def test_exported_function(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/utils.ts", "/project")
        multiply = _find_node(nodes, name="multiply", kind=NodeKind.FUNCTION)
        assert multiply is not None
        assert multiply.properties.get("exported") is True

    def test_exported_arrow_function(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/utils.ts", "/project")
        divide = _find_node(nodes, name="divide", kind=NodeKind.FUNCTION)
        assert divide is not None
        assert divide.properties.get("exported") is True


# ---------------------------------------------------------------------------
# Test 3: Imports (ES6 named, default, namespace, CommonJS)
# ---------------------------------------------------------------------------
class TestImports:
    SOURCE = b"""\
import { UserService, RoleService } from './services/user';
import DefaultExport from 'some-module';
import * as Utils from '../utils';
const lodash = require('lodash');

function doSomething() {}
"""

    def test_named_imports_stored(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/app.ts", "/project")
        # Find the module node for the file
        mod = _find_node(nodes, name="app", kind=NodeKind.MODULE)
        assert mod is not None
        imports = mod.properties.get("imports", [])
        # Should have entries for all import statements
        named = [i for i in imports if i.get("kind") == "named"]
        assert len(named) >= 2  # UserService, RoleService

    def test_default_import_stored(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/app.ts", "/project")
        mod = _find_node(nodes, name="app", kind=NodeKind.MODULE)
        imports = mod.properties.get("imports", [])
        default = [i for i in imports if i.get("kind") == "default"]
        assert len(default) >= 1
        assert default[0]["local_name"] == "DefaultExport"
        assert default[0]["module"] == "some-module"

    def test_namespace_import_stored(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/app.ts", "/project")
        mod = _find_node(nodes, name="app", kind=NodeKind.MODULE)
        imports = mod.properties.get("imports", [])
        ns = [i for i in imports if i.get("kind") == "namespace"]
        assert len(ns) >= 1
        assert ns[0]["local_name"] == "Utils"

    def test_commonjs_require_stored(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/app.ts", "/project")
        mod = _find_node(nodes, name="app", kind=NodeKind.MODULE)
        imports = mod.properties.get("imports", [])
        cjs = [i for i in imports if i.get("kind") == "commonjs"]
        assert len(cjs) >= 1
        assert cjs[0]["local_name"] == "lodash"
        assert cjs[0]["module"] == "lodash"


# ---------------------------------------------------------------------------
# Test 4: Method calls
# ---------------------------------------------------------------------------
class TestMethodCalls:
    SOURCE = b"""\
class OrderService {
    private repo: OrderRepository;

    constructor(repo: OrderRepository) {
        this.repo = repo;
    }

    async findOrder(id: string): Promise<Order> {
        const order = await this.repo.findById(id);
        console.log("Found order");
        return order;
    }

    async createOrder(data: CreateOrderDto): Promise<Order> {
        const validated = validate(data);
        return this.repo.save(validated);
    }
}
"""

    def test_this_method_call(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/order.ts", "/project")
        call = _find_edge(
            edges,
            kind=EdgeKind.CALLS,
            source_contains="findOrder",
            target_contains="findById",
        )
        assert call is not None
        assert call.confidence == Confidence.LOW  # unresolved

    def test_function_call(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/order.ts", "/project")
        call = _find_edge(
            edges,
            kind=EdgeKind.CALLS,
            source_contains="createOrder",
            target_contains="validate",
        )
        assert call is not None

    def test_multiple_calls_from_same_method(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/order.ts", "/project")
        calls_from_create = _find_edges(
            edges, kind=EdgeKind.CALLS, source_contains="createOrder"
        )
        # validate() and this.repo.save()
        assert len(calls_from_create) >= 2


# ---------------------------------------------------------------------------
# Test 5: Decorators (NestJS-style)
# ---------------------------------------------------------------------------
class TestDecorators:
    SOURCE = b"""\
@Controller('users')
@UseGuards(AuthGuard)
class UserController {
    @Get(':id')
    async getUser(@Param('id') id: string): Promise<User> {
        return this.service.findById(id);
    }

    @Post()
    @HttpCode(201)
    async createUser(@Body() dto: CreateUserDto): Promise<User> {
        return this.service.create(dto);
    }
}
"""

    def test_class_decorators_stored(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(
            self.SOURCE, "src/user.controller.ts", "/project"
        )
        ctrl = _find_node(nodes, name="UserController", kind=NodeKind.CLASS)
        assert ctrl is not None
        annotations = ctrl.properties.get("annotations", [])
        decorator_names = [a["name"] for a in annotations]
        assert "Controller" in decorator_names
        assert "UseGuards" in decorator_names

    def test_controller_decorator_args(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(
            self.SOURCE, "src/user.controller.ts", "/project"
        )
        ctrl = _find_node(nodes, name="UserController", kind=NodeKind.CLASS)
        annotations = ctrl.properties.get("annotations", [])
        controller_ann = next(a for a in annotations if a["name"] == "Controller")
        assert controller_ann["arguments"] == ["users"]

    def test_method_decorators_stored(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(
            self.SOURCE, "src/user.controller.ts", "/project"
        )
        get_user = _find_node(nodes, name="getUser", kind=NodeKind.FUNCTION)
        assert get_user is not None
        annotations = get_user.properties.get("annotations", [])
        decorator_names = [a["name"] for a in annotations]
        assert "Get" in decorator_names

    def test_method_decorator_args(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(
            self.SOURCE, "src/user.controller.ts", "/project"
        )
        get_user = _find_node(nodes, name="getUser", kind=NodeKind.FUNCTION)
        annotations = get_user.properties.get("annotations", [])
        get_ann = next(a for a in annotations if a["name"] == "Get")
        assert get_ann["arguments"] == [":id"]


# ---------------------------------------------------------------------------
# Test 6: JSX elements (React component references)
# ---------------------------------------------------------------------------
class TestJSXElements:
    SOURCE = b"""\
import React from 'react';
import { Header } from './Header';
import { Footer } from './Footer';
import { UserCard } from './UserCard';

export function App() {
    const users = [{ name: 'Alice' }];
    return (
        <div className="app">
            <Header title="My App" />
            <main>
                {users.map(u => (
                    <UserCard key={u.name} user={u} />
                ))}
            </main>
            <Footer />
        </div>
    );
}
"""

    def test_jsx_components_captured(self, extractor: TypeScriptExtractor):
        # Use .tsx extension to trigger TSX parser
        nodes, edges = extractor.extract(self.SOURCE, "src/App.tsx", "/project")
        app_fn = _find_node(nodes, name="App", kind=NodeKind.FUNCTION)
        assert app_fn is not None
        jsx_elements = app_fn.properties.get("jsx_elements", [])
        # Should capture PascalCase components, not HTML elements like div/main
        component_names = [j["name"] for j in jsx_elements]
        assert "Header" in component_names
        assert "Footer" in component_names
        assert "UserCard" in component_names
        assert "div" not in component_names
        assert "main" not in component_names

    def test_jsx_component_count(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/App.tsx", "/project")
        app_fn = _find_node(nodes, name="App", kind=NodeKind.FUNCTION)
        jsx_elements = app_fn.properties.get("jsx_elements", [])
        component_names = [j["name"] for j in jsx_elements]
        assert len(component_names) == 3


# ---------------------------------------------------------------------------
# Test 7: Interface declarations
# ---------------------------------------------------------------------------
class TestInterface:
    SOURCE = b"""\
export interface IUser {
    id: string;
    name: string;
    email: string;
    createdAt: Date;
}

interface IRepository<T> {
    findById(id: string): Promise<T>;
    save(entity: T): Promise<T>;
    delete(id: string): Promise<void>;
}
"""

    def test_interface_nodes_created(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/types.ts", "/project")
        iuser = _find_node(nodes, name="IUser", kind=NodeKind.INTERFACE)
        irepo = _find_node(nodes, name="IRepository", kind=NodeKind.INTERFACE)
        assert iuser is not None
        assert irepo is not None
        assert iuser.fqn == "src/types.IUser"
        assert irepo.fqn == "src/types.IRepository"

    def test_interface_exported(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/types.ts", "/project")
        iuser = _find_node(nodes, name="IUser", kind=NodeKind.INTERFACE)
        assert iuser.properties.get("exported") is True

    def test_interface_language(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/types.ts", "/project")
        iuser = _find_node(nodes, name="IUser", kind=NodeKind.INTERFACE)
        assert iuser.language == "typescript"


# ---------------------------------------------------------------------------
# Test 8: Export declarations
# ---------------------------------------------------------------------------
class TestExports:
    SOURCE = b"""\
export default class MainService {
    run(): void {}
}

export { helper, formatter } from './utils';

export const API_URL = 'http://localhost:3000';

function internalHelper() {}
"""

    def test_default_export_class(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/main.ts", "/project")
        main_svc = _find_node(nodes, name="MainService", kind=NodeKind.CLASS)
        assert main_svc is not None
        assert main_svc.properties.get("exported") is True
        assert main_svc.properties.get("export_kind") == "default"

    def test_non_exported_function(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/main.ts", "/project")
        helper = _find_node(nodes, name="internalHelper", kind=NodeKind.FUNCTION)
        assert helper is not None
        assert helper.properties.get("exported") is not True

    def test_exported_const(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/main.ts", "/project")
        # API_URL is a const, not a function or class, so not extracted as a node
        # But the module should track named exports
        mod = _find_node(nodes, name="main", kind=NodeKind.MODULE)
        exports = mod.properties.get("exports", [])
        export_names = [e["name"] for e in exports]
        assert "API_URL" in export_names


# ---------------------------------------------------------------------------
# Test 9: JavaScript file extension
# ---------------------------------------------------------------------------
class TestJavaScriptFile:
    SOURCE = b"""\
function greet(name) {
    console.log("Hello " + name);
}

class App {
    run() {
        greet("world");
    }
}
"""

    def test_js_file_language(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/app.js", "/project")
        mod = _find_node(nodes, name="app", kind=NodeKind.MODULE)
        assert mod is not None
        assert mod.language == "javascript"

    def test_js_class_language(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/app.js", "/project")
        app = _find_node(nodes, name="App", kind=NodeKind.CLASS)
        assert app is not None
        assert app.language == "javascript"

    def test_js_function_extracted(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(self.SOURCE, "src/app.js", "/project")
        greet = _find_node(nodes, name="greet", kind=NodeKind.FUNCTION)
        assert greet is not None
        assert greet.language == "javascript"


# ---------------------------------------------------------------------------
# Test 10: Full file integration test
# ---------------------------------------------------------------------------
class TestFullFile:
    SOURCE = b"""\
import { Injectable } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { User } from './user.entity';
import { CreateUserDto } from './dto/create-user.dto';

@Injectable()
export class UserService {
    constructor(
        @InjectRepository(User)
        private readonly userRepository: Repository<User>,
    ) {}

    async findAll(): Promise<User[]> {
        return this.userRepository.find();
    }

    async findOne(id: number): Promise<User | undefined> {
        return this.userRepository.findOneBy({ id });
    }

    async create(createUserDto: CreateUserDto): Promise<User> {
        const user = this.userRepository.create(createUserDto);
        return this.userRepository.save(user);
    }

    async remove(id: number): Promise<void> {
        await this.userRepository.delete(id);
    }
}
"""

    def test_module_node_created(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(
            self.SOURCE, "src/user/user.service.ts", "/project"
        )
        mod = _find_node(nodes, name="user.service", kind=NodeKind.MODULE)
        assert mod is not None
        assert mod.fqn == "src/user/user.service"

    def test_class_node(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(
            self.SOURCE, "src/user/user.service.ts", "/project"
        )
        cls = _find_node(nodes, name="UserService", kind=NodeKind.CLASS)
        assert cls is not None
        assert cls.fqn == "src/user/user.service.UserService"
        assert cls.properties.get("exported") is True
        annotations = cls.properties.get("annotations", [])
        assert any(a["name"] == "Injectable" for a in annotations)

    def test_method_nodes(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(
            self.SOURCE, "src/user/user.service.ts", "/project"
        )
        methods = [
            n for n in nodes if n.kind == NodeKind.FUNCTION and "UserService" in n.fqn
        ]
        method_names = {m.name for m in methods}
        assert "findAll" in method_names
        assert "findOne" in method_names
        assert "create" in method_names
        assert "remove" in method_names

    def test_contains_edges(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(
            self.SOURCE, "src/user/user.service.ts", "/project"
        )
        contains = _find_edges(
            edges, kind=EdgeKind.CONTAINS, source_contains="UserService"
        )
        # At least 4 methods contained
        assert len(contains) >= 4

    def test_calls_edges(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(
            self.SOURCE, "src/user/user.service.ts", "/project"
        )
        calls = _find_edges(edges, kind=EdgeKind.CALLS)
        # find, findOneBy, create, save, delete
        assert len(calls) >= 5

    def test_imports_captured(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(
            self.SOURCE, "src/user/user.service.ts", "/project"
        )
        mod = _find_node(nodes, name="user.service", kind=NodeKind.MODULE)
        imports = mod.properties.get("imports", [])
        modules = {i["module"] for i in imports}
        assert "@nestjs/common" in modules
        assert "@nestjs/typeorm" in modules
        assert "typeorm" in modules
        assert "./user.entity" in modules
        assert "./dto/create-user.dto" in modules

    def test_total_node_count(self, extractor: TypeScriptExtractor):
        nodes, edges = extractor.extract(
            self.SOURCE, "src/user/user.service.ts", "/project"
        )
        # 1 module + 1 class + 4 methods = 6 minimum
        assert len(nodes) >= 6
