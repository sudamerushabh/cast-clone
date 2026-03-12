# M9: Integration Wiring & End-to-End Tests Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 9 no-op stage stubs in `pipeline.py` with real stage implementations from M3–M7d, wire dependencies (Neo4jGraphStore, PluginRegistry), add a comprehensive Spring PetClinic test fixture, and verify the full pipeline end-to-end.

**Architecture:** M2 created `pipeline.py` with no-op `_stage_*` functions and a `_STAGE_FUNCS` dict mapping stage names to callables. This milestone replaces each stub with a thin wrapper that calls the real stage function from M3–M7d, passing the correct arguments from `AnalysisContext` and injected services. The pipeline function gains a `services` parameter (or loads them from the app state) so it can pass `GraphStore`, `PluginRegistry`, etc. to stages that need them. Integration tests use `testcontainers-python` for Neo4j and PostgreSQL, or mock them where full infra is too heavy.

**Tech Stack:** Python 3.12, FastAPI, pytest + pytest-asyncio, testcontainers-python (neo4j, postgres), structlog

**Dependencies:** ALL prior milestones (M1–M7d)

---

## File Structure

```
cast-clone-backend/
├── app/
│   └── orchestrator/
│       └── pipeline.py                   # MODIFY — replace stubs with real stage calls
├── tests/
│   ├── conftest.py                       # MODIFY — add shared fixtures
│   ├── fixtures/
│   │   └── spring-petclinic/             # CREATE — realistic Java test fixture
│   │       ├── pom.xml
│   │       ├── src/main/java/org/springframework/samples/petclinic/
│   │       │   ├── PetClinicApplication.java
│   │       │   ├── owner/
│   │       │   │   ├── Owner.java
│   │       │   │   ├── OwnerRepository.java
│   │       │   │   └── OwnerController.java
│   │       │   ├── vet/
│   │       │   │   ├── Vet.java
│   │       │   │   ├── VetRepository.java
│   │       │   │   └── VetController.java
│   │       │   └── pet/
│   │       │       ├── Pet.java
│   │       │       ├── PetRepository.java
│   │       │       └── PetType.java
│   │       └── src/main/resources/
│   │           ├── application.properties
│   │           └── db/migration/
│   │               └── V1__init.sql
│   ├── integration/
│   │   ├── __init__.py                   # CREATE
│   │   ├── conftest.py                   # CREATE — testcontainers fixtures
│   │   ├── test_pipeline_e2e.py          # CREATE — full pipeline integration test
│   │   └── test_neo4j_roundtrip.py       # CREATE — write + query roundtrip
│   └── unit/
│       └── test_pipeline_wiring.py       # CREATE — verify stage functions are wired correctly
```

---

## Task 1: Spring PetClinic Test Fixture

**Files:**
- Create: `tests/fixtures/spring-petclinic/pom.xml`
- Create: `tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/PetClinicApplication.java`
- Create: `tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/owner/Owner.java`
- Create: `tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/owner/OwnerRepository.java`
- Create: `tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/owner/OwnerController.java`
- Create: `tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/vet/Vet.java`
- Create: `tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/vet/VetRepository.java`
- Create: `tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/vet/VetController.java`
- Create: `tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/pet/Pet.java`
- Create: `tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/pet/PetRepository.java`
- Create: `tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/pet/PetType.java`
- Create: `tests/fixtures/spring-petclinic/src/main/resources/application.properties`
- Create: `tests/fixtures/spring-petclinic/src/main/resources/db/migration/V1__init.sql`

- [ ] **Step 1: Create pom.xml**

```xml
<!-- tests/fixtures/spring-petclinic/pom.xml -->
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>
    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>3.2.0</version>
    </parent>
    <groupId>org.springframework.samples</groupId>
    <artifactId>spring-petclinic</artifactId>
    <version>3.2.0-SNAPSHOT</version>
    <name>petclinic</name>

    <dependencies>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-web</artifactId>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-data-jpa</artifactId>
        </dependency>
        <dependency>
            <groupId>org.flywaydb</groupId>
            <artifactId>flyway-core</artifactId>
        </dependency>
        <dependency>
            <groupId>org.postgresql</groupId>
            <artifactId>postgresql</artifactId>
            <scope>runtime</scope>
        </dependency>
    </dependencies>
</project>
```

- [ ] **Step 2: Create PetClinicApplication.java**

```java
// tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/PetClinicApplication.java
package org.springframework.samples.petclinic;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class PetClinicApplication {
    public static void main(String[] args) {
        SpringApplication.run(PetClinicApplication.class, args);
    }
}
```

- [ ] **Step 3: Create Owner.java (JPA entity)**

```java
// tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/owner/Owner.java
package org.springframework.samples.petclinic.owner;

import jakarta.persistence.*;
import java.util.ArrayList;
import java.util.List;

@Entity
@Table(name = "owners")
public class Owner {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(name = "first_name")
    private String firstName;

    @Column(name = "last_name")
    private String lastName;

    @Column(name = "address")
    private String address;

    @Column(name = "city")
    private String city;

    @Column(name = "telephone")
    private String telephone;

    @OneToMany(cascade = CascadeType.ALL, mappedBy = "owner", fetch = FetchType.EAGER)
    private List<org.springframework.samples.petclinic.pet.Pet> pets = new ArrayList<>();

    public Integer getId() { return id; }
    public void setId(Integer id) { this.id = id; }
    public String getFirstName() { return firstName; }
    public void setFirstName(String firstName) { this.firstName = firstName; }
    public String getLastName() { return lastName; }
    public void setLastName(String lastName) { this.lastName = lastName; }
    public String getAddress() { return address; }
    public void setAddress(String address) { this.address = address; }
    public String getCity() { return city; }
    public void setCity(String city) { this.city = city; }
    public String getTelephone() { return telephone; }
    public void setTelephone(String telephone) { this.telephone = telephone; }
    public List<org.springframework.samples.petclinic.pet.Pet> getPets() { return pets; }
}
```

- [ ] **Step 4: Create OwnerRepository.java**

```java
// tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/owner/OwnerRepository.java
package org.springframework.samples.petclinic.owner;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import java.util.List;

public interface OwnerRepository extends JpaRepository<Owner, Integer> {

    @Query("SELECT DISTINCT owner FROM Owner owner LEFT JOIN FETCH owner.pets WHERE owner.lastName LIKE :lastName%")
    List<Owner> findByLastName(@Param("lastName") String lastName);

    List<Owner> findByCity(String city);
}
```

- [ ] **Step 5: Create OwnerController.java**

```java
// tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/owner/OwnerController.java
package org.springframework.samples.petclinic.owner;

import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController
@RequestMapping("/api/owners")
public class OwnerController {

    private final OwnerRepository ownerRepository;

    public OwnerController(OwnerRepository ownerRepository) {
        this.ownerRepository = ownerRepository;
    }

    @GetMapping
    public List<Owner> listOwners() {
        return ownerRepository.findAll();
    }

    @GetMapping("/{ownerId}")
    public Owner getOwner(@PathVariable int ownerId) {
        return ownerRepository.findById(ownerId)
                .orElseThrow(() -> new RuntimeException("Owner not found"));
    }

    @PostMapping
    public Owner createOwner(@RequestBody Owner owner) {
        return ownerRepository.save(owner);
    }

    @GetMapping("/search")
    public List<Owner> findByLastName(@RequestParam String lastName) {
        return ownerRepository.findByLastName(lastName);
    }
}
```

- [ ] **Step 6: Create Vet.java, VetRepository.java, VetController.java**

```java
// tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/vet/Vet.java
package org.springframework.samples.petclinic.vet;

import jakarta.persistence.*;

@Entity
@Table(name = "vets")
public class Vet {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(name = "first_name")
    private String firstName;

    @Column(name = "last_name")
    private String lastName;

    public Integer getId() { return id; }
    public void setId(Integer id) { this.id = id; }
    public String getFirstName() { return firstName; }
    public void setFirstName(String firstName) { this.firstName = firstName; }
    public String getLastName() { return lastName; }
    public void setLastName(String lastName) { this.lastName = lastName; }
}
```

```java
// tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/vet/VetRepository.java
package org.springframework.samples.petclinic.vet;

import org.springframework.data.jpa.repository.JpaRepository;

public interface VetRepository extends JpaRepository<Vet, Integer> {
}
```

```java
// tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/vet/VetController.java
package org.springframework.samples.petclinic.vet;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import java.util.List;

@RestController
@RequestMapping("/api/vets")
public class VetController {

    private final VetRepository vetRepository;

    public VetController(VetRepository vetRepository) {
        this.vetRepository = vetRepository;
    }

    @GetMapping
    public List<Vet> listVets() {
        return vetRepository.findAll();
    }
}
```

- [ ] **Step 7: Create Pet.java, PetRepository.java, PetType.java**

```java
// tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/pet/Pet.java
package org.springframework.samples.petclinic.pet;

import jakarta.persistence.*;
import org.springframework.samples.petclinic.owner.Owner;
import java.time.LocalDate;

@Entity
@Table(name = "pets")
public class Pet {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(name = "name")
    private String name;

    @Column(name = "birth_date")
    private LocalDate birthDate;

    @ManyToOne
    @JoinColumn(name = "type_id")
    private PetType type;

    @ManyToOne
    @JoinColumn(name = "owner_id")
    private Owner owner;

    public Integer getId() { return id; }
    public void setId(Integer id) { this.id = id; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public LocalDate getBirthDate() { return birthDate; }
    public void setBirthDate(LocalDate birthDate) { this.birthDate = birthDate; }
    public PetType getType() { return type; }
    public void setType(PetType type) { this.type = type; }
    public Owner getOwner() { return owner; }
    public void setOwner(Owner owner) { this.owner = owner; }
}
```

```java
// tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/pet/PetRepository.java
package org.springframework.samples.petclinic.pet;

import org.springframework.data.jpa.repository.JpaRepository;

public interface PetRepository extends JpaRepository<Pet, Integer> {
}
```

```java
// tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/pet/PetType.java
package org.springframework.samples.petclinic.pet;

import jakarta.persistence.*;

@Entity
@Table(name = "types")
public class PetType {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(name = "name")
    private String name;

    public Integer getId() { return id; }
    public void setId(Integer id) { this.id = id; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
}
```

- [ ] **Step 8: Create application.properties and Flyway migration**

```properties
# tests/fixtures/spring-petclinic/src/main/resources/application.properties
spring.datasource.url=jdbc:postgresql://localhost:5432/petclinic
spring.datasource.username=petclinic
spring.datasource.password=petclinic
spring.jpa.hibernate.ddl-auto=validate
spring.flyway.enabled=true
```

```sql
-- tests/fixtures/spring-petclinic/src/main/resources/db/migration/V1__init.sql
CREATE TABLE IF NOT EXISTS vets (
    id SERIAL PRIMARY KEY,
    first_name VARCHAR(30),
    last_name VARCHAR(30)
);

CREATE TABLE IF NOT EXISTS types (
    id SERIAL PRIMARY KEY,
    name VARCHAR(80)
);

CREATE TABLE IF NOT EXISTS owners (
    id SERIAL PRIMARY KEY,
    first_name VARCHAR(30),
    last_name VARCHAR(30),
    address VARCHAR(255),
    city VARCHAR(80),
    telephone VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS pets (
    id SERIAL PRIMARY KEY,
    name VARCHAR(30),
    birth_date DATE,
    type_id INT NOT NULL REFERENCES types(id),
    owner_id INT NOT NULL REFERENCES owners(id)
);

CREATE TABLE IF NOT EXISTS visits (
    id SERIAL PRIMARY KEY,
    pet_id INT NOT NULL REFERENCES pets(id),
    visit_date DATE,
    description VARCHAR(255)
);
```

- [ ] **Step 9: Commit**

```bash
cd cast-clone-backend && git add tests/fixtures/spring-petclinic/ && git commit -m "test(fixtures): add Spring PetClinic fixture for integration testing"
```

---

## Task 2: Pipeline Wiring — Replace Stubs with Real Stage Calls

**Files:**
- Modify: `app/orchestrator/pipeline.py`
- Create: `tests/unit/test_pipeline_wiring.py`

This is the core of M9: replace each `_stage_*` no-op with a call to the real implementation.

- [ ] **Step 1: Write the wiring verification test**

```python
# tests/unit/test_pipeline_wiring.py
"""Verify that pipeline stage functions are wired to real implementations, not no-ops."""

from __future__ import annotations

import inspect

import pytest

from app.orchestrator.pipeline import _STAGE_FUNCS


class TestPipelineWiring:
    """Ensure every stage function calls real code, not a pass statement."""

    def test_discovery_is_wired(self):
        """Stage 1 should call discover_project from stages.discovery."""
        func = _STAGE_FUNCS["discovery"]
        source = inspect.getsource(func)
        assert "discover_project" in source

    def test_dependencies_is_wired(self):
        """Stage 2 should call resolve_dependencies from stages.dependencies."""
        func = _STAGE_FUNCS["dependencies"]
        source = inspect.getsource(func)
        assert "resolve_dependencies" in source

    def test_parsing_is_wired(self):
        """Stage 3 should call parse_with_treesitter from stages.treesitter."""
        func = _STAGE_FUNCS["parsing"]
        source = inspect.getsource(func)
        assert "parse_with_treesitter" in source

    def test_scip_is_wired(self):
        """Stage 4 should call run_scip_indexers from stages.scip."""
        func = _STAGE_FUNCS["scip"]
        source = inspect.getsource(func)
        assert "run_scip_indexers" in source

    def test_plugins_is_wired(self):
        """Stage 5 should call run_framework_plugins from stages.plugins."""
        func = _STAGE_FUNCS["plugins"]
        source = inspect.getsource(func)
        assert "run_framework_plugins" in source or "plugin_registry" in source

    def test_linking_is_wired(self):
        """Stage 6 should call run_cross_tech_linker from stages.linker."""
        func = _STAGE_FUNCS["linking"]
        source = inspect.getsource(func)
        assert "run_cross_tech_linker" in source

    def test_enrichment_is_wired(self):
        """Stage 7 should call enrich_graph from stages.enricher."""
        func = _STAGE_FUNCS["enrichment"]
        source = inspect.getsource(func)
        assert "enrich_graph" in source

    def test_writing_is_wired(self):
        """Stage 8 should call write_to_neo4j from stages.writer."""
        func = _STAGE_FUNCS["writing"]
        source = inspect.getsource(func)
        assert "write_to_neo4j" in source

    def test_transactions_is_wired(self):
        """Stage 9 should call discover_transactions from stages.transactions."""
        func = _STAGE_FUNCS["transactions"]
        source = inspect.getsource(func)
        assert "discover_transactions" in source

    def test_all_stages_present(self):
        """All 10 stage names should be in _STAGE_FUNCS."""
        expected = {
            "discovery", "dependencies", "parsing", "scip",
            "lsp_fallback", "plugins", "linking", "enrichment",
            "writing", "transactions",
        }
        assert set(_STAGE_FUNCS.keys()) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pipeline_wiring.py -v`
Expected: FAIL — all stage functions currently contain only `pass`

- [ ] **Step 3: Add PipelineServices dataclass and refactor pipeline.py**

Replace the no-op stubs in `app/orchestrator/pipeline.py` with real wiring. The key changes:

1. Add a `PipelineServices` dataclass to hold injected dependencies
2. Replace each `_stage_*` function body with a call to the real stage function
3. Update `run_analysis_pipeline` to accept/create `PipelineServices`

```python
# app/orchestrator/pipeline.py
"""Analysis pipeline orchestrator — runs 9 stages sequentially.

Each stage function delegates to the real implementation from app.stages.*.
Services (GraphStore, PluginRegistry) are injected via PipelineServices.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Coroutine, Any

from sqlalchemy import select

from app.models.context import AnalysisContext
from app.models.db import Project, AnalysisRun
from app.orchestrator.progress import WebSocketProgressReporter
from app.services.neo4j import GraphStore

logger = logging.getLogger(__name__)


@dataclass
class PipelineServices:
    """Injected dependencies for the pipeline stages."""

    graph_store: GraphStore
    source_path: Path
    project_name: str


@dataclass
class PipelineStage:
    """Definition of a single pipeline stage."""

    name: str
    description: str
    critical: bool = False  # If True, failure aborts the pipeline


# ── Stage wrapper functions ──────────────────────────────────────────────
# Each function accepts (context, services) and delegates to the real stage.


async def _stage_discovery(context: AnalysisContext, services: PipelineServices) -> None:
    """Stage 1: Discover project files, languages, frameworks."""
    from app.stages.discovery import discover_project

    context.manifest = await discover_project(services.source_path)


async def _stage_dependencies(context: AnalysisContext, services: PipelineServices) -> None:
    """Stage 2: Resolve build dependencies."""
    from app.stages.dependencies import resolve_dependencies

    assert context.manifest is not None, "Stage 1 (discovery) must run first"
    context.environment = await resolve_dependencies(context.manifest)


async def _stage_parsing(context: AnalysisContext, services: PipelineServices) -> None:
    """Stage 3: Parse source files with tree-sitter."""
    from app.stages.treesitter.parser import parse_with_treesitter

    assert context.manifest is not None, "Stage 1 (discovery) must run first"
    graph = await parse_with_treesitter(context.manifest)
    context.graph.merge(graph)


async def _stage_scip(context: AnalysisContext, services: PipelineServices) -> None:
    """Stage 4: Run SCIP indexers for type resolution."""
    from app.stages.scip.indexer import run_scip_indexers
    from app.stages.scip.merger import merge_scip_into_graph

    assert context.manifest is not None, "Stage 1 (discovery) must run first"
    scip_results = await run_scip_indexers(context.manifest, context.environment)
    for lang, scip_data in scip_results.items():
        merge_scip_into_graph(scip_data, context.graph)
        context.scip_resolved_languages.add(lang)


async def _stage_lsp_fallback(context: AnalysisContext, services: PipelineServices) -> None:
    """Stage 4b: LSP fallback for languages where SCIP failed.

    Only runs if there are languages that SCIP didn't cover.
    Currently a no-op — LSP fallback is deferred to later phases.
    """
    if context.manifest is not None:
        all_langs = set(context.manifest.languages)
        covered = context.scip_resolved_languages
        missing = all_langs - covered
        if missing:
            context.languages_needing_fallback = list(missing)
            logger.info(
                "pipeline.lsp_fallback.skipped",
                extra={"languages": list(missing), "reason": "LSP fallback not yet implemented"},
            )


async def _stage_plugins(context: AnalysisContext, services: PipelineServices) -> None:
    """Stage 5: Run framework-specific plugins."""
    from app.stages.plugins.registry import PluginRegistry

    assert context.manifest is not None, "Stage 1 (discovery) must run first"
    registry = PluginRegistry()
    results = await registry.run_applicable(context)
    context.plugin_new_nodes = sum(r.nodes_added for r in results)
    context.plugin_new_edges = sum(r.edges_added for r in results)


async def _stage_linking(context: AnalysisContext, services: PipelineServices) -> None:
    """Stage 6: Link cross-technology dependencies."""
    from app.stages.linker import run_cross_tech_linker

    await run_cross_tech_linker(context)


async def _stage_enrichment(context: AnalysisContext, services: PipelineServices) -> None:
    """Stage 7: Compute metrics and run community detection."""
    from app.stages.enricher import enrich_graph

    await enrich_graph(context)


async def _stage_writing(context: AnalysisContext, services: PipelineServices) -> None:
    """Stage 8: Write graph to Neo4j."""
    from app.stages.writer import write_to_neo4j

    await write_to_neo4j(context, services.graph_store, services.project_name)


async def _stage_transactions(context: AnalysisContext, services: PipelineServices) -> None:
    """Stage 9: Discover transaction flows."""
    from app.stages.transactions import discover_transactions

    await discover_transactions(context)


# ── Stage registry ────────────────────────────────────────────────────────

StageFunc = Callable[[AnalysisContext, PipelineServices], Coroutine[Any, Any, None]]


PIPELINE_STAGES: list[PipelineStage] = [
    PipelineStage("discovery", "Scanning filesystem...", critical=True),
    PipelineStage("dependencies", "Resolving dependencies..."),
    PipelineStage("parsing", "Parsing source files..."),
    PipelineStage("scip", "Running SCIP indexers..."),
    PipelineStage("lsp_fallback", "LSP fallback for unsupported languages..."),
    PipelineStage("plugins", "Running framework plugins..."),
    PipelineStage("linking", "Linking cross-technology dependencies..."),
    PipelineStage("enrichment", "Computing metrics and communities..."),
    PipelineStage("writing", "Writing to database...", critical=True),
    PipelineStage("transactions", "Discovering transaction flows..."),
]

_STAGE_FUNCS: dict[str, StageFunc] = {
    "discovery": _stage_discovery,
    "dependencies": _stage_dependencies,
    "parsing": _stage_parsing,
    "scip": _stage_scip,
    "lsp_fallback": _stage_lsp_fallback,
    "plugins": _stage_plugins,
    "linking": _stage_linking,
    "enrichment": _stage_enrichment,
    "writing": _stage_writing,
    "transactions": _stage_transactions,
}


def _get_session_factory():
    """Get the async session factory. Separated for testability."""
    from app.services.postgres import _session_factory

    assert _session_factory is not None, "PostgreSQL not initialized"
    return _session_factory


# ── Main pipeline function ────────────────────────────────────────────────


async def run_analysis_pipeline(
    project_id: str,
    services: PipelineServices | None = None,
) -> None:
    """Run the full 9-stage analysis pipeline.

    Called as a FastAPI BackgroundTask. Loads the project from DB,
    runs each stage sequentially, updates status, and reports progress
    via WebSocket.

    Args:
        project_id: UUID of the project to analyze.
        services: Injected pipeline services. If None, loads from app state.

    Raises:
        ValueError: If the project is not found in the database.
    """
    session_factory = _get_session_factory()
    ws = WebSocketProgressReporter(project_id)
    pipeline_start = time.monotonic()

    async with session_factory() as session:
        # Load project
        result = await session.execute(
            select(Project).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        if project is None:
            raise ValueError(f"Project {project_id} not found")

        # Build services if not injected
        if services is None:
            from app.services.neo4j import get_graph_store

            graph_store = get_graph_store()
            services = PipelineServices(
                graph_store=graph_store,
                source_path=Path(project.source_path),
                project_name=project.name,
            )

        # Create analysis run record
        run = AnalysisRun(
            project_id=project_id,
            status="running",
        )
        session.add(run)

        # Update project status
        project.status = "analyzing"
        await session.commit()

        # Initialize context
        context = AnalysisContext(project_id=project_id)

        # Run each stage
        for stage_def in PIPELINE_STAGES:
            stage_func = _STAGE_FUNCS[stage_def.name]
            stage_start = time.monotonic()

            try:
                await ws.emit(stage_def.name, "running", stage_def.description)
                logger.info(
                    "pipeline.stage.start",
                    extra={"project_id": project_id, "stage": stage_def.name},
                )

                await stage_func(context, services)

                elapsed = time.monotonic() - stage_start
                await ws.emit(
                    stage_def.name,
                    "complete",
                    details={"duration_seconds": round(elapsed, 2)},
                )
                logger.info(
                    "pipeline.stage.complete",
                    extra={
                        "project_id": project_id,
                        "stage": stage_def.name,
                        "duration": round(elapsed, 2),
                    },
                )

                # Track current stage in run record
                run.stage = stage_def.name

            except Exception as e:
                elapsed = time.monotonic() - stage_start
                logger.error(
                    "pipeline.stage.failed",
                    extra={
                        "project_id": project_id,
                        "stage": stage_def.name,
                        "error": str(e),
                        "duration": round(elapsed, 2),
                    },
                )
                await ws.emit(
                    stage_def.name,
                    "failed",
                    message=str(e),
                    details={"duration_seconds": round(elapsed, 2)},
                )

                if stage_def.critical:
                    # Critical stage failure — abort pipeline
                    project.status = "failed"
                    run.status = "failed"
                    run.error_message = f"Critical stage '{stage_def.name}' failed: {e}"
                    await session.commit()
                    await ws.emit_error(
                        f"Pipeline aborted: critical stage '{stage_def.name}' failed: {e}"
                    )
                    raise
                else:
                    # Non-critical — warn and continue
                    context.warnings.append(
                        f"Stage '{stage_def.name}' failed: {e}"
                    )

        # Pipeline complete
        total_elapsed = time.monotonic() - pipeline_start
        project.status = "analyzed"
        run.status = "completed"
        run.node_count = context.graph.node_count
        run.edge_count = context.graph.edge_count
        await session.commit()

        report = {
            "total_nodes": context.graph.node_count,
            "total_edges": context.graph.edge_count,
            "warnings": context.warnings,
            "duration_seconds": round(total_elapsed, 2),
        }
        await ws.emit_complete(report)

        logger.info(
            "pipeline.complete",
            extra={
                "project_id": project_id,
                "duration": round(total_elapsed, 2),
                "nodes": context.graph.node_count,
                "edges": context.graph.edge_count,
                "warnings": len(context.warnings),
            },
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_pipeline_wiring.py -v`
Expected: PASS (all wiring tests)

- [ ] **Step 5: Commit**

```bash
cd cast-clone-backend && git add app/orchestrator/pipeline.py tests/unit/test_pipeline_wiring.py && git commit -m "feat(pipeline): wire all 9 stage stubs to real implementations"
```

---

## Task 3: Integration Test Fixtures (testcontainers)

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/conftest.py`
- Modify: `tests/conftest.py` — add `FIXTURE_DIR` constant

- [ ] **Step 1: Add testcontainers dependency**

Run: `cd cast-clone-backend && uv add --dev testcontainers`

- [ ] **Step 2: Create integration test conftest**

```python
# tests/integration/__init__.py
```

```python
# tests/integration/conftest.py
"""Integration test fixtures using testcontainers.

Provides real Neo4j and PostgreSQL instances for testing.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio
from testcontainers.neo4j import Neo4jContainer
from testcontainers.postgres import PostgresContainer

from app.models.context import AnalysisContext
from app.services.neo4j import Neo4jGraphStore


FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"
PETCLINIC_DIR = FIXTURE_DIR / "spring-petclinic"


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop for async fixtures."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def neo4j_container():
    """Start a Neo4j container for the test session."""
    with Neo4jContainer("neo4j:5-community") as neo4j:
        yield neo4j


@pytest.fixture(scope="session")
def neo4j_uri(neo4j_container):
    """Get the bolt URI for the Neo4j test container."""
    return neo4j_container.get_connection_url()


@pytest_asyncio.fixture
async def graph_store(neo4j_container) -> Neo4jGraphStore:
    """Create a Neo4jGraphStore connected to the test container."""
    uri = neo4j_container.get_connection_url()
    auth = ("neo4j", "test")  # testcontainers default
    store = Neo4jGraphStore(uri=uri, auth=auth)
    await store.connect()
    yield store
    # Clean up after each test
    await store.query("MATCH (n) DETACH DELETE n", {})
    await store.close()


@pytest.fixture
def petclinic_path() -> Path:
    """Path to the Spring PetClinic test fixture."""
    assert PETCLINIC_DIR.exists(), f"PetClinic fixture not found at {PETCLINIC_DIR}"
    return PETCLINIC_DIR


@pytest.fixture
def analysis_context() -> AnalysisContext:
    """Create a fresh AnalysisContext for testing."""
    return AnalysisContext(project_id="test-project")
```

- [ ] **Step 3: Update root conftest with FIXTURE_DIR**

Add to `tests/conftest.py`:

```python
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures"
```

- [ ] **Step 4: Commit**

```bash
cd cast-clone-backend && git add tests/integration/ tests/conftest.py && git commit -m "test(integration): add testcontainers conftest for Neo4j integration tests"
```

---

## Task 4: Neo4j Write + Query Roundtrip Test

**Files:**
- Create: `tests/integration/test_neo4j_roundtrip.py`

- [ ] **Step 1: Write the integration test**

```python
# tests/integration/test_neo4j_roundtrip.py
"""Integration test: write a SymbolGraph to Neo4j and query it back.

Uses testcontainers for a real Neo4j instance.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.models.context import AnalysisContext
from app.models.enums import Confidence, EdgeKind, NodeKind
from app.models.graph import GraphEdge, GraphNode, SymbolGraph
from app.stages.writer import write_to_neo4j


@pytest.mark.integration
class TestNeo4jRoundtrip:
    """Write a graph and verify it's queryable."""

    @pytest.fixture
    def sample_graph(self) -> SymbolGraph:
        """Build a small but realistic graph."""
        graph = SymbolGraph()

        # Module
        graph.add_node(GraphNode(
            fqn="org.petclinic",
            name="petclinic",
            kind=NodeKind.MODULE,
            language="java",
        ))

        # Class
        graph.add_node(GraphNode(
            fqn="org.petclinic.Owner",
            name="Owner",
            kind=NodeKind.CLASS,
            language="java",
            path="src/main/java/org/petclinic/Owner.java",
            line=10,
            end_line=50,
            loc=40,
        ))

        # Method
        graph.add_node(GraphNode(
            fqn="org.petclinic.Owner.getName",
            name="getName",
            kind=NodeKind.METHOD,
            language="java",
            path="src/main/java/org/petclinic/Owner.java",
            line=30,
            end_line=32,
            loc=3,
        ))

        # Edges
        graph.add_edge(GraphEdge(
            source_fqn="org.petclinic",
            target_fqn="org.petclinic.Owner",
            kind=EdgeKind.CONTAINS,
        ))
        graph.add_edge(GraphEdge(
            source_fqn="org.petclinic.Owner",
            target_fqn="org.petclinic.Owner.getName",
            kind=EdgeKind.CONTAINS,
        ))

        return graph

    @pytest.mark.asyncio
    async def test_write_and_query_nodes(self, graph_store, sample_graph):
        """Write nodes and verify count matches."""
        context = AnalysisContext(project_id="test-roundtrip")
        context.graph = sample_graph

        await write_to_neo4j(context, graph_store, "test-petclinic")

        # Query back
        result = await graph_store.query(
            "MATCH (n) WHERE n.fqn IS NOT NULL RETURN count(n) AS cnt",
            {},
        )
        assert result[0]["cnt"] == 3  # module + class + method

    @pytest.mark.asyncio
    async def test_write_and_query_edges(self, graph_store, sample_graph):
        """Write edges and verify relationships exist."""
        context = AnalysisContext(project_id="test-roundtrip")
        context.graph = sample_graph

        await write_to_neo4j(context, graph_store, "test-petclinic")

        result = await graph_store.query(
            "MATCH ()-[r:CONTAINS]->() RETURN count(r) AS cnt",
            {},
        )
        assert result[0]["cnt"] == 2

    @pytest.mark.asyncio
    async def test_write_and_query_by_label(self, graph_store, sample_graph):
        """Verify nodes have correct labels."""
        context = AnalysisContext(project_id="test-roundtrip")
        context.graph = sample_graph

        await write_to_neo4j(context, graph_store, "test-petclinic")

        classes = await graph_store.query(
            "MATCH (c:Class) RETURN c.fqn AS fqn", {},
        )
        assert len(classes) == 1
        assert classes[0]["fqn"] == "org.petclinic.Owner"

        methods = await graph_store.query(
            "MATCH (m:Method) RETURN m.fqn AS fqn", {},
        )
        assert len(methods) == 1
        assert methods[0]["fqn"] == "org.petclinic.Owner.getName"

    @pytest.mark.asyncio
    async def test_application_node_created(self, graph_store, sample_graph):
        """Verify the Application root node is created."""
        context = AnalysisContext(project_id="test-roundtrip")
        context.graph = sample_graph

        await write_to_neo4j(context, graph_store, "test-petclinic")

        result = await graph_store.query(
            "MATCH (a:Application) RETURN a.name AS name", {},
        )
        assert len(result) == 1
        assert result[0]["name"] == "test-petclinic"
```

- [ ] **Step 2: Run test to verify it passes (requires Docker)**

Run: `cd cast-clone-backend && uv run pytest tests/integration/test_neo4j_roundtrip.py -v -m integration`
Expected: PASS (all 4 tests)

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend && git add tests/integration/test_neo4j_roundtrip.py && git commit -m "test(integration): add Neo4j write/query roundtrip tests"
```

---

## Task 5: Pipeline End-to-End Test (Stages 1-3 only)

**Files:**
- Create: `tests/integration/test_pipeline_e2e.py`

This test runs stages 1-3 (discovery + dependencies + tree-sitter) against the PetClinic fixture. Stages 4-9 are mocked since they need external tools (SCIP) or Neo4j.

- [ ] **Step 1: Write the end-to-end test**

```python
# tests/integration/test_pipeline_e2e.py
"""End-to-end pipeline test: run stages 1-3 against Spring PetClinic fixture.

Stages 4-9 require external tooling (SCIP, Neo4j) and are tested separately.
This test verifies the in-memory pipeline from discovery through tree-sitter parsing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from app.models.context import AnalysisContext
from app.models.enums import NodeKind, EdgeKind


FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"
PETCLINIC_DIR = FIXTURE_DIR / "spring-petclinic"


@pytest.mark.integration
class TestPipelineStages1Through3:
    """Run stages 1-3 sequentially against PetClinic fixture."""

    @pytest.mark.asyncio
    async def test_discovery_finds_java_files(self):
        """Stage 1: Discovery should find all .java files."""
        from app.stages.discovery import discover_project

        manifest = await discover_project(PETCLINIC_DIR)

        assert "java" in manifest.languages
        assert manifest.total_files > 0
        # Should find at least Owner.java, OwnerController.java, etc.
        java_files = [f for f in manifest.source_files if f.path.endswith(".java")]
        assert len(java_files) >= 8  # 11 Java files in fixture

    @pytest.mark.asyncio
    async def test_discovery_detects_spring(self):
        """Stage 1: Discovery should detect Spring Boot framework."""
        from app.stages.discovery import discover_project

        manifest = await discover_project(PETCLINIC_DIR)

        assert "spring-boot" in manifest.frameworks or "spring" in manifest.frameworks

    @pytest.mark.asyncio
    async def test_discovery_detects_maven(self):
        """Stage 1: Discovery should detect Maven build tool."""
        from app.stages.discovery import discover_project

        manifest = await discover_project(PETCLINIC_DIR)

        assert manifest.build_tool == "maven" or "maven" in str(manifest.build_tools)

    @pytest.mark.asyncio
    async def test_treesitter_parses_java(self):
        """Stage 3: Tree-sitter should extract classes and methods from Java files."""
        from app.stages.discovery import discover_project
        from app.stages.treesitter.parser import parse_with_treesitter

        manifest = await discover_project(PETCLINIC_DIR)
        graph = await parse_with_treesitter(manifest)

        # Should find Owner, OwnerController, OwnerRepository, etc.
        class_nodes = [n for n in graph.nodes.values() if n.kind == NodeKind.CLASS]
        assert len(class_nodes) >= 5  # Owner, OwnerController, Vet, VetController, Pet, PetType

        # Should find methods
        method_nodes = [n for n in graph.nodes.values() if n.kind == NodeKind.METHOD]
        assert len(method_nodes) >= 5  # getters, controller methods

    @pytest.mark.asyncio
    async def test_treesitter_extracts_relationships(self):
        """Stage 3: Tree-sitter should extract CONTAINS and CALLS edges."""
        from app.stages.discovery import discover_project
        from app.stages.treesitter.parser import parse_with_treesitter

        manifest = await discover_project(PETCLINIC_DIR)
        graph = await parse_with_treesitter(manifest)

        # CONTAINS edges: class contains methods
        contains_edges = [e for e in graph.edges if e.kind == EdgeKind.CONTAINS]
        assert len(contains_edges) > 0

    @pytest.mark.asyncio
    async def test_stages_1_through_3_sequential(self):
        """Run stages 1-3 in sequence, verify cumulative result."""
        from app.stages.discovery import discover_project
        from app.stages.dependencies import resolve_dependencies
        from app.stages.treesitter.parser import parse_with_treesitter

        # Stage 1: Discovery
        manifest = await discover_project(PETCLINIC_DIR)
        assert manifest is not None

        # Stage 2: Dependencies
        environment = await resolve_dependencies(manifest)
        assert environment is not None

        # Stage 3: Tree-sitter parsing
        graph = await parse_with_treesitter(manifest)
        assert graph.node_count > 0
        assert graph.edge_count > 0

        # Compose into context
        context = AnalysisContext(project_id="test-e2e")
        context.manifest = manifest
        context.environment = environment
        context.graph = graph

        # Verify context state
        assert context.graph.node_count > 10  # Should have many nodes
        assert len(context.warnings) == 0  # No warnings expected

    @pytest.mark.asyncio
    async def test_sql_migration_detected(self):
        """Stage 1+3: SQL migration files should be discovered."""
        from app.stages.discovery import discover_project

        manifest = await discover_project(PETCLINIC_DIR)

        # Should find V1__init.sql
        sql_files = [f for f in manifest.source_files if f.path.endswith(".sql")]
        assert len(sql_files) >= 1
```

- [ ] **Step 2: Run test**

Run: `cd cast-clone-backend && uv run pytest tests/integration/test_pipeline_e2e.py -v -m integration`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend && git add tests/integration/test_pipeline_e2e.py && git commit -m "test(integration): add end-to-end pipeline test for stages 1-3"
```

---

## Task 6: pytest Configuration for Integration Tests

**Files:**
- Modify: `pyproject.toml` — add pytest markers and integration test config

- [ ] **Step 1: Add pytest markers to pyproject.toml**

Add to the `[tool.pytest.ini_options]` section:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = [
    "integration: marks tests that require external services (Docker)",
]
testpaths = ["tests"]
```

- [ ] **Step 2: Commit**

```bash
cd cast-clone-backend && git add pyproject.toml && git commit -m "chore: add pytest integration marker config"
```

---

## Task 7: Update analysis.py API to Pass Services

**Files:**
- Modify: `app/api/analysis.py` — update pipeline invocation to build PipelineServices

- [ ] **Step 1: Update the trigger endpoint**

In `app/api/analysis.py`, where `run_analysis_pipeline` is called as a background task, update it to build `PipelineServices`:

```python
# In the trigger_analysis endpoint:
from app.orchestrator.pipeline import run_analysis_pipeline, PipelineServices
from app.services.neo4j import get_graph_store
from pathlib import Path

# When creating the background task:
services = PipelineServices(
    graph_store=get_graph_store(),
    source_path=Path(project.source_path),
    project_name=project.name,
)
background_tasks.add_task(run_analysis_pipeline, project_id, services)
```

- [ ] **Step 2: Run existing API tests to verify no regression**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_analysis_api.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend && git add app/api/analysis.py && git commit -m "feat(api): pass PipelineServices to analysis pipeline"
```

---

## Task 8: Final Verification

- [ ] **Step 1: Run all unit tests**

Run: `cd cast-clone-backend && uv run pytest tests/unit/ -v --tb=short`
Expected: All PASS

- [ ] **Step 2: Run integration tests (if Docker available)**

Run: `cd cast-clone-backend && uv run pytest tests/integration/ -v -m integration --tb=short`
Expected: All PASS

- [ ] **Step 3: Run linting**

Run: `cd cast-clone-backend && uv run ruff check app/ tests/ && uv run ruff format --check app/ tests/`
Expected: No errors

- [ ] **Step 4: Run type checking**

Run: `cd cast-clone-backend && uv run mypy app/orchestrator/pipeline.py`
Expected: No errors

- [ ] **Step 5: Final commit**

```bash
cd cast-clone-backend && git add -A && git commit -m "feat(m9): complete pipeline integration wiring with end-to-end tests"
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | Spring PetClinic test fixture | 13 files in `tests/fixtures/spring-petclinic/` |
| 2 | Replace pipeline stubs with real stage calls | `app/orchestrator/pipeline.py` |
| 3 | Integration test infrastructure (testcontainers) | `tests/integration/conftest.py` |
| 4 | Neo4j write/query roundtrip test | `tests/integration/test_neo4j_roundtrip.py` |
| 5 | Pipeline E2E test (stages 1-3) | `tests/integration/test_pipeline_e2e.py` |
| 6 | pytest integration marker config | `pyproject.toml` |
| 7 | API endpoint wiring update | `app/api/analysis.py` |
| 8 | Final verification (all tests + linting) | — |

**Key design decisions:**
- Stage functions now take `(context, services)` instead of just `(context)` — allows dependency injection of `GraphStore`
- `PipelineServices` is a simple dataclass, not a DI container — YAGNI
- LSP fallback (Stage 4b) remains a no-op with logging — deferred to later phases
- Integration tests use `testcontainers-python` for real Neo4j, not mocks
- E2E test covers stages 1-3 only (pure Python, no external tools needed)
- Neo4j roundtrip test validates the write→query cycle with real Neo4j
