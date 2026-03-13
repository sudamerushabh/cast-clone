"""Deterministic triage: categorize changed files and build code batches."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field


# --- File categorization patterns ---

_CATEGORY_PATTERNS: list[tuple[str, list[str]]] = [
    ("migration", [
        "*/migrations/*", "*/db/migrate/*", "*flyway*", "*liquibase*",
        "*/alembic/versions/*", "*/alembic/*",
        "alembic/versions/*", "alembic/*",
    ]),
    ("test", [
        "*/test_*", "*/tests/*", "*_test.*", "*.test.*", "*.spec.*",
        "*/test/*", "*/__tests__/*",
    ]),
    ("infra", [
        "Dockerfile", "docker-compose*", "*.dockerfile",
        ".github/workflows/*", ".gitlab-ci*", "Jenkinsfile",
        "*.tf", "*.tfvars", "helm/*", "k8s/*", "kubernetes/*",
    ]),
    ("config", [
        ".env", ".env.*", "*.yml", "*.yaml", "*.toml", "*.ini", "*.cfg",
        "*.properties", "application.*", "*.config.*", "*.json",
        "pyproject.toml", "package.json", "tsconfig.json",
    ]),
    ("docs", [
        "*.md", "*.rst", "*.txt", "docs/*", "README*", "CHANGELOG*",
        "LICENSE*",
    ]),
]

# Source extensions — if nothing else matches and has a code extension
_SOURCE_EXTENSIONS = {
    ".java", ".py", ".ts", ".tsx", ".js", ".jsx", ".cs", ".go",
    ".rs", ".kt", ".scala", ".rb", ".php", ".swift", ".cpp", ".c",
    ".h", ".hpp",
}

# Language prefixes to strip when inferring module from path
_LANG_PREFIXES = [
    "src/main/java/", "src/main/kotlin/", "src/main/scala/",
    "src/main/resources/", "src/", "app/", "lib/", "pkg/",
]


def categorize_file(path: str) -> str:
    """Categorize a file path into test/migration/infra/config/docs/source."""
    normalized = path.replace("\\", "/")

    for category, patterns in _CATEGORY_PATTERNS:
        for pattern in patterns:
            if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(
                normalized.split("/")[-1], pattern
            ):
                return category

    # Check if it's a source file by extension
    for ext in _SOURCE_EXTENSIONS:
        if normalized.endswith(ext):
            return "source"

    return "source"  # Default to source


def _infer_module_from_path(path: str) -> str:
    """Infer a module name from a file path by stripping language prefixes.

    Uses the parent directory of the file as the module name, which gives
    meaningful grouping (e.g., com/example/service/Foo.java -> service).
    """
    normalized = path.replace("\\", "/")

    for prefix in _LANG_PREFIXES:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
            break

    parts = normalized.split("/")
    # Use the parent directory (second-to-last segment) as module
    # This groups files in the same package/directory together
    if len(parts) > 2:
        # For deep paths like com/example/service/Foo.java, use parent dir
        return parts[-2]
    if len(parts) > 1:
        return parts[0]
    return "root"


def _module_from_fqn(fqn: str) -> str:
    """Extract module from a fully-qualified name (first 3 segments)."""
    parts = fqn.split(".")
    return ".".join(parts[:3]) if len(parts) >= 3 else fqn


@dataclass
class CodeBatch:
    """A batch of source files grouped by module for a sub-agent."""

    batch_id: str
    files: list[str] = field(default_factory=list)
    graph_node_fqns: list[str] = field(default_factory=list)


@dataclass
class TriageResult:
    """Result of deterministic triage of a diff."""

    code_batches: list[CodeBatch] = field(default_factory=list)
    config_files: list[str] = field(default_factory=list)
    infra_files: list[str] = field(default_factory=list)
    migration_files: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    doc_files: list[str] = field(default_factory=list)
    env_vars_referenced: list[str] = field(default_factory=list)
    total_subagents: int = 0


def triage_diff(
    diff: dict[str, str],
    changed_nodes: list[dict] | None = None,
    max_subagents: int = 15,
) -> TriageResult:
    """Triage a diff into categorized files and code batches.

    Args:
        diff: Mapping of file path -> diff content.
        changed_nodes: List of graph nodes with 'fqn' and 'file' keys.
        max_subagents: Maximum number of sub-agents to spawn.

    Returns:
        TriageResult with categorized files and code batches.
    """
    changed_nodes = changed_nodes or []

    result = TriageResult()

    source_files: list[str] = []

    # Step 1: Categorize all files
    for path in diff:
        category = categorize_file(path)
        if category == "source":
            source_files.append(path)
        elif category == "test":
            result.test_files.append(path)
        elif category == "migration":
            result.migration_files.append(path)
        elif category == "infra":
            result.infra_files.append(path)
        elif category == "config":
            result.config_files.append(path)
        elif category == "docs":
            result.doc_files.append(path)

    # Step 2: Build file-to-FQN mapping from graph nodes
    file_to_fqns: dict[str, list[str]] = {}
    fqn_to_module: dict[str, str] = {}
    for node in changed_nodes:
        fqn = node.get("fqn", "")
        file_path = node.get("file", "")
        if file_path and fqn:
            file_to_fqns.setdefault(file_path, []).append(fqn)
            fqn_to_module[fqn] = _module_from_fqn(fqn)

    # Step 3: Group source files by module
    module_files: dict[str, list[str]] = {}
    module_fqns: dict[str, list[str]] = {}

    for path in source_files:
        # Prefer graph-based module from FQN
        fqns = file_to_fqns.get(path, [])
        if fqns:
            module = fqn_to_module.get(fqns[0], _infer_module_from_path(path))
        else:
            module = _infer_module_from_path(path)

        module_files.setdefault(module, []).append(path)
        for fqn in fqns:
            module_fqns.setdefault(module, []).append(fqn)

    # Step 4: Build batches, max 5 files per batch
    batches: list[CodeBatch] = []
    for module, files in sorted(module_files.items()):
        fqns = module_fqns.get(module, [])
        for i in range(0, len(files), 5):
            chunk = files[i : i + 5]
            chunk_fqns = fqns[i : i + 5] if fqns else []
            batch_id = f"{module}_{len(batches)}"
            batches.append(
                CodeBatch(
                    batch_id=batch_id,
                    files=chunk,
                    graph_node_fqns=chunk_fqns,
                )
            )

    # Step 5: Circuit breaker — merge smallest batches if too many
    reserved_agents = 3  # infra, config, test-gap agents
    max_code_batches = max_subagents - reserved_agents

    while len(batches) > max_code_batches and len(batches) > 1:
        # Sort by file count, merge two smallest
        batches.sort(key=lambda b: len(b.files))
        smallest = batches.pop(0)
        second_smallest = batches.pop(0)
        merged = CodeBatch(
            batch_id=f"merged_{smallest.batch_id}_{second_smallest.batch_id}",
            files=smallest.files + second_smallest.files,
            graph_node_fqns=smallest.graph_node_fqns
            + second_smallest.graph_node_fqns,
        )
        batches.append(merged)

    result.code_batches = batches
    result.total_subagents = len(batches) + reserved_agents

    return result
