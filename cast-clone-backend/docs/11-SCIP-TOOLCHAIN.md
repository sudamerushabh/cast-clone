# SCIP Toolchain — Installation & Integration Guide

## What is SCIP?

SCIP (SCIP Code Intelligence Protocol) is a batch indexing protocol from Sourcegraph that produces protobuf files containing symbol definitions, references, and type relationships for an entire codebase. Unlike LSP (which is request/response for editors), SCIP is purpose-built for batch indexing — making it 10x faster for whole-project analysis.

In our pipeline, SCIP is **Stage 4**: it takes the raw symbol graph from tree-sitter (Stage 3) and upgrades it with type-resolved cross-references, precise FQNs, and implementation relationships.

```
Tree-sitter (Stage 3)     SCIP (Stage 4)          Merged Graph
─────────────────────  →  ──────────────────  →  ──────────────
- Structure only           - Type resolution       - HIGH confidence edges
- LOW confidence edges     - Cross-references      - Precise FQNs
- Heuristic FQNs           - IMPLEMENTS edges      - Documentation
```

## Supported Language Indexers

| Language | Indexer | Command | Notes |
|----------|---------|---------|-------|
| Java/Scala/Kotlin | `scip-java` | `scip-java index` | Requires JDK + Maven/Gradle; instruments the compiler |
| TypeScript/JavaScript | `scip-typescript` | `npx @sourcegraph/scip-typescript index` | Uses Pyright-based analysis |
| Python | `scip-python` | `scip-python index . --project-name=NAME` | Uses Pyright; requires project name |
| C#/.NET | `scip-dotnet` | `scip-dotnet index` | Requires .NET SDK |

All indexers produce a single `index.scip` protobuf file in the project root.

---

## Prerequisites

### System Requirements

- **OS:** Linux (Ubuntu 22.04+), macOS, or Windows with WSL
- **RAM:** 4GB+ recommended (Maven compilation + SCIP indexing)
- **Disk:** ~500MB for JDK + Maven + scip-java

### Java Toolchain (for scip-java)

```bash
# JDK 17+ required (21 recommended)
sudo apt-get update
sudo apt-get install -y default-jdk

# Verify
java -version   # Should show 17+ or 21+
javac -version  # MUST have javac (JDK, not just JRE)
```

> **Important:** You need the full JDK (with `javac`), not just the JRE. scip-java compiles the project and instruments the compiler to extract type information.

### Maven (for Maven-based Java projects)

```bash
sudo apt-get install -y maven

# Verify
mvn --version  # Should show 3.8+
```

> **Note:** If the project uses Gradle instead, scip-java auto-detects `build.gradle` and uses the Gradle wrapper. No separate Gradle install needed.

---

## Installing scip-java

### Method 1: Coursier (Recommended)

[Coursier](https://get-coursier.io/) is a Scala/Java tool launcher that can bootstrap scip-java as a standalone fat JAR.

```bash
# 1. Download Coursier
curl -fL https://github.com/coursier/coursier/releases/latest/download/cs-x86_64-pc-linux.gz | gzip -d > /tmp/coursier
chmod +x /tmp/coursier

# 2. Install scip-java to ~/.local/bin
mkdir -p ~/.local/bin
/tmp/coursier bootstrap \
  --main com.sourcegraph.scip_java.ScipJava \
  -r sonatype:snapshots \
  com.sourcegraph:scip-java_2.13:0.11.2 \
  -o ~/.local/bin/scip-java \
  --standalone

chmod +x ~/.local/bin/scip-java

# 3. Add to PATH (add to ~/.bashrc for persistence)
export PATH="$HOME/.local/bin:$PATH"

# 4. Verify
scip-java --help
```

### Method 2: Docker (No local install)

```bash
docker run --rm \
  -v "$(pwd):/src" \
  -w /src \
  sourcegraph/scip-java:latest \
  scip-java index
```

Our pipeline supports Docker-based indexing via the `docker_image` field in `SCIPIndexerConfig`, though the current implementation uses local binaries.

### Method 3: Direct JAR download

```bash
# Download the fat JAR from Maven Central
curl -L "https://repo1.maven.org/maven2/com/sourcegraph/scip-java_2.13/0.11.2/scip-java_2.13-0.11.2-assembly.jar" \
  -o ~/.local/bin/scip-java.jar

# Create a wrapper script
cat > ~/.local/bin/scip-java << 'EOF'
#!/bin/bash
exec java -jar "$(dirname "$0")/scip-java.jar" "$@"
EOF
chmod +x ~/.local/bin/scip-java
```

---

## How scip-java Works

scip-java performs a full compilation of the target project and instruments the Java compiler to capture type information:

```
Source Code (.java)
       │
       ▼
   Maven/Gradle compile
   (with scip-java compiler plugin)
       │
       ▼
   Instrumented javac captures:
   - Symbol definitions (classes, methods, fields)
   - Cross-references (who calls what, with types)
   - Implementation relationships (class → interface)
   - Generic type parameters
   - Documentation (Javadoc)
       │
       ▼
   index.scip (protobuf binary)
```

### What scip-java produces

The `index.scip` file contains:

1. **Documents** — one per source file, with:
   - **Occurrences** — every symbol usage with line/column range
     - `symbol_roles` bit flags: DEFINITION, REFERENCE, WRITE_ACCESS, READ_ACCESS
   - **SymbolInformation** — metadata per symbol:
     - Documentation (Javadoc text)
     - Relationships (e.g., `ClassA implements InterfaceB`)

2. **Symbol format** — globally unique identifiers:
   ```
   maven . com/example 1.0 UserService#
   maven . com/example 1.0 UserService#createUser().
   maven . com/example 1.0 UserService#name.
   ```
   Format: `<scheme> <manager> <package> <version> <descriptor>`

### Build artifacts

scip-java creates build artifacts in the project directory:
- `target/` (Maven) or `build/` (Gradle) — compiled classes
- `index.scip` — the protobuf output file

These are cleaned up after indexing. Add to `.gitignore`:
```
**/target/
index.scip
*.scip
```

---

## Pipeline Integration

### Architecture

```
app/stages/scip/
├── indexer.py          # Orchestrates SCIP indexer subprocesses
├── protobuf_parser.py  # Parses index.scip protobuf wire format
└── merger.py           # Merges SCIP data into SymbolGraph
```

### Stage 4 Flow

```python
# indexer.py: run_scip_indexers(context)
#
# 1. Detect which languages have SCIP indexers
# 2. Build CLI commands for each indexer
# 3. Run all indexers in parallel (asyncio.gather)
# 4. Parse each index.scip with protobuf_parser
# 5. Merge results into SymbolGraph via merger
# 6. Languages that fail → queued for LSP fallback (Stage 4b)
```

### Indexer Configuration

Defined in `indexer.py` as `SCIP_INDEXER_CONFIGS`:

```python
SCIPIndexerConfig(
    language="java",
    name="scip-java",
    command_template=["scip-java", "index"],
    timeout_seconds=600,       # 10 minutes
    output_file="index.scip",
    docker_image="sourcegraph/scip-java:latest",
)
```

The indexer runs as an async subprocess via `run_subprocess()` which:
- Inherits `os.environ` (so scip-java must be on PATH)
- Sets `cwd` to the project root
- Enforces a configurable timeout (default 600s)

### Protobuf Parser

`protobuf_parser.py` uses **raw protobuf wire-format parsing** — no generated code or proto compiler needed. It reads the binary `index.scip` and produces Python dataclasses:

```
SCIPIndex
├── metadata_tool_name: str
├── metadata_tool_version: str
└── documents: list[SCIPDocument]
    ├── relative_path: str
    ├── occurrences: list[SCIPOccurrence]
    │   ├── range: list[int]    # [line, start_col, end_col] or [start_line, start_col, end_line, end_col]
    │   ├── symbol: str         # SCIP symbol identifier
    │   └── symbol_roles: int   # Bit flags (DEFINITION=0x1, REFERENCE=no flag, etc.)
    └── symbols: list[SCIPSymbolInfo]
        ├── symbol: str
        ├── documentation: list[str]
        └── relationships: list[SCIPRelationship]
            ├── symbol: str
            ├── is_implementation: bool
            └── is_type_definition: bool
```

### Merger Algorithm

`merger.py` performs a 3-pass merge into the existing SymbolGraph:

**Pass 1 — Definitions:**
- For each SCIP definition occurrence, find matching GraphNode by FQN or file:line
- Upgrade node FQN if SCIP provides a more precise one
- Add Javadoc documentation to node properties

**Pass 2 — References:**
- For each SCIP reference, find the containing function (caller) by file:line
- Find the target symbol (callee) by FQN
- Upgrade existing CALLS edge confidence from LOW → HIGH

**Pass 3 — Relationships:**
- For SCIP `is_implementation` relationships, add/upgrade IMPLEMENTS edges with HIGH confidence

### Symbol FQN Conversion

SCIP symbols are converted to internal FQNs by `scip_symbol_to_fqn()`:

```
SCIP:     maven . com/example 1.0 UserService#createUser().
Internal: com.example.UserService.createUser

SCIP:     maven . org/springframework/samples/petclinic/owner 1.0 OwnerController#
Internal: org.springframework.samples.petclinic.owner.OwnerController
```

Conversion rules:
- Package: `/` → `.`, strip `@` prefix
- Class descriptor `#` → removed
- Method descriptor `().` → removed
- Field descriptor `.` (trailing) → removed

---

## Graceful Degradation

SCIP is **not fatal** — if it fails, the pipeline continues with tree-sitter results:

| Scenario | Behavior |
|----------|----------|
| scip-java / scip-typescript / scip-python / scip-dotnet not installed | Stage 4 **pre-flights** `shutil.which(binary)` (CHAN-71), skips the indexer with a warning that carries the install hint, and queues the language for LSP fallback — no subprocess launch |
| Maven compile fails | Warning + fallback |
| index.scip empty/corrupt | Warning, no merge performed |
| Timeout (>600s) | Subprocess killed, language queued for fallback |
| Partial success (multi-lang) | Each language handled independently |

Only Stage 1 (discovery) and Stage 8 (Neo4j write) are fatal. Everything else degrades gracefully.

### Install hints

Each indexer config carries an `install_hint` pointing back at this doc. When a
binary is missing, the warning log event `scip.indexer.binary_not_on_path`
(emitted by `detect_available_indexers`) includes `install_hint` so operators
can wire a log alert that surfaces the install command directly — no need to
dig through Stage 4 traces.

---

## Performance Characteristics

Benchmarked against Spring PetClinic (10 Java files, ~1600 LOC):

| Phase | Duration | Notes |
|-------|----------|-------|
| Maven compile | ~4.5s | First run; cached builds are faster |
| SCIP indexing | ~0.5s | After compilation |
| Protobuf parsing | <0.01s | Raw wire-format parsing is fast |
| Merge | <0.01s | 3-pass algorithm over graph |
| **Total Stage 4** | **~5.0s** | Dominated by Maven compilation |

For larger projects (100k+ LOC), expect:
- Maven compile: 30-120s
- SCIP indexing: 5-30s
- The 600s timeout should cover most projects

---

## Troubleshooting

### `scip-java: command not found`

Ensure scip-java is on PATH:
```bash
which scip-java
# If not found:
export PATH="$HOME/.local/bin:$PATH"
# Add to ~/.bashrc for persistence
```

### `javac: command not found`

You have JRE but not JDK. Install the full JDK:
```bash
sudo apt-get install default-jdk
javac -version  # Should now work
```

### `release version 17 not supported`

Your JDK is too old. Install JDK 17+:
```bash
sudo apt-get install openjdk-21-jdk
java -version
```

### Maven compile errors

scip-java needs to compile the project successfully. Common fixes:
```bash
# Try compiling manually first
cd /path/to/project
mvn compile -q

# If it fails, check:
# 1. Missing dependencies → run `mvn dependency:resolve`
# 2. Wrong Java version → check pom.xml <maven.compiler.source>
# 3. Missing parent POM → check if multi-module project needs `mvn install` from root
```

### `index.scip not found after indexing`

scip-java may have exited with code 0 but produced no output:
```bash
# Run manually with verbose output
scip-java index --verbose 2>&1 | tail -20

# Check if target/ was created (compilation happened)
ls -la target/
```

### Permission denied writing to /usr/local/bin

Install to user directory instead:
```bash
mkdir -p ~/.local/bin
# Re-run Coursier with -o ~/.local/bin/scip-java
```

### Slow first run

The first Maven compile downloads dependencies. Subsequent runs use the local `~/.m2/repository` cache and are significantly faster.

---

## Installing Other SCIP Indexers

### scip-typescript (TypeScript/JavaScript)

```bash
# No global install needed — runs via npx
npx @sourcegraph/scip-typescript index

# Or install globally
npm install -g @sourcegraph/scip-typescript
```

### scip-python

```bash
pip install scip-python
# Or
pipx install scip-python

# Usage
scip-python index . --project-name=myproject
```

### scip-dotnet (C#/.NET)

```bash
dotnet tool install --global scip-dotnet

# Usage
scip-dotnet index
```

---

## References

- [SCIP Protocol Specification](https://github.com/sourcegraph/scip/blob/main/scip.proto)
- [scip-java Repository](https://github.com/sourcegraph/scip-java)
- [Sourcegraph Code Intelligence Docs](https://sourcegraph.com/docs/code-intelligence)
- [Coursier Installation](https://get-coursier.io/docs/cli-installation)
