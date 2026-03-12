# M3: Project Discovery & Dependency Resolution Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Stage 1 (Project Discovery) and Stage 2 (Dependency Resolution) of the analysis pipeline, plus all test fixtures needed by later milestones. After M3, the system can scan any codebase, identify its languages/frameworks/build tools, count lines of code, and parse dependency declarations from build files.

**Architecture:** `discover_project()` is a synchronous function (filesystem I/O is fast). `resolve_dependencies()` is async (future-proofing for subprocess calls). Both produce dataclasses defined in M1. Discovery is a critical stage (failure = abort pipeline). Dependency resolution is non-critical (failure = warn, continue with reduced SCIP accuracy). All functions use structlog for JSON logging with timing at entry/exit.

**Tech Stack:** Python 3.12, structlog, pathlib, tomllib (stdlib), xml.etree.ElementTree (stdlib), json (stdlib), pytest + pytest-asyncio

**Depends on M1:** `ProjectManifest`, `SourceFile`, `DetectedLanguage`, `DetectedFramework`, `BuildTool`, `ResolvedEnvironment`, `ResolvedDependency`, `Confidence` enum.

---

## File Structure

```
cast-clone-backend/
├── app/
│   └── stages/
│       ├── __init__.py              # CREATE — empty
│       ├── discovery.py             # CREATE — discover_project()
│       └── dependencies.py          # CREATE — resolve_dependencies()
├── tests/
│   ├── conftest.py                  # CREATE — shared fixtures (tmp_path helpers)
│   ├── __init__.py                  # CREATE — empty
│   ├── unit/
│   │   ├── __init__.py              # CREATE — empty
│   │   ├── test_discovery.py        # CREATE — Stage 1 tests
│   │   └── test_dependencies.py     # CREATE — Stage 2 tests
│   └── fixtures/
│       ├── raw-java/
│       │   ├── pom.xml                                              # CREATE
│       │   ├── src/main/java/com/example/UserService.java           # CREATE
│       │   └── src/main/java/com/example/UserController.java        # CREATE
│       ├── express-app/
│       │   ├── package.json                                         # CREATE
│       │   └── src/index.js                                         # CREATE
│       └── spring-petclinic/
│           ├── pom.xml                                              # CREATE
│           └── src/main/java/org/springframework/samples/petclinic/
│               ├── PetClinicApplication.java                        # CREATE
│               ├── owner/OwnerController.java                       # CREATE
│               ├── owner/OwnerRepository.java                       # CREATE
│               ├── owner/Owner.java                                 # CREATE
│               └── vet/VetController.java                           # CREATE
```

---

## Task 1: Test Fixtures — Raw Java Project

**Files:**
- Create: `tests/fixtures/raw-java/pom.xml`
- Create: `tests/fixtures/raw-java/src/main/java/com/example/UserService.java`
- Create: `tests/fixtures/raw-java/src/main/java/com/example/UserController.java`

- [ ] **Step 1: Create the pom.xml**

```xml
<!-- tests/fixtures/raw-java/pom.xml -->
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
         https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>3.2.0</version>
    </parent>

    <groupId>com.example</groupId>
    <artifactId>user-service</artifactId>
    <version>1.0.0</version>

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
            <groupId>org.hibernate.orm</groupId>
            <artifactId>hibernate-core</artifactId>
            <version>6.4.0.Final</version>
        </dependency>
        <dependency>
            <groupId>com.h2database</groupId>
            <artifactId>h2</artifactId>
            <scope>runtime</scope>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-test</artifactId>
            <scope>test</scope>
        </dependency>
    </dependencies>
</project>
```

- [ ] **Step 2: Create UserService.java**

```java
// tests/fixtures/raw-java/src/main/java/com/example/UserService.java
package com.example;

import org.springframework.stereotype.Service;
import org.springframework.beans.factory.annotation.Autowired;
import java.util.List;
import java.util.Optional;

@Service
public class UserService {

    @Autowired
    private UserRepository userRepository;

    public List<User> findAll() {
        return userRepository.findAll();
    }

    public Optional<User> findById(Long id) {
        return userRepository.findById(id);
    }

    public User create(User user) {
        validateUser(user);
        return userRepository.save(user);
    }

    private void validateUser(User user) {
        if (user.getName() == null || user.getName().isEmpty()) {
            throw new IllegalArgumentException("Name is required");
        }
    }
}
```

- [ ] **Step 3: Create UserController.java**

```java
// tests/fixtures/raw-java/src/main/java/com/example/UserController.java
package com.example;

import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.beans.factory.annotation.Autowired;
import java.util.List;

@RestController
@RequestMapping("/api/users")
public class UserController {

    @Autowired
    private UserService userService;

    @GetMapping
    public List<User> listUsers() {
        return userService.findAll();
    }

    @GetMapping("/{id}")
    public User getUser(@PathVariable Long id) {
        return userService.findById(id)
                .orElseThrow(() -> new RuntimeException("User not found"));
    }

    @PostMapping
    public User createUser(@RequestBody User user) {
        return userService.create(user);
    }
}
```

- [ ] **Step 4: Commit fixtures**

```bash
cd cast-clone-backend && git add tests/fixtures/raw-java/ && git commit -m "test(fixtures): add raw-java fixture with Spring Boot pom.xml and source files"
```

---

## Task 2: Test Fixtures — Express App

**Files:**
- Create: `tests/fixtures/express-app/package.json`
- Create: `tests/fixtures/express-app/src/index.js`

- [ ] **Step 1: Create package.json**

```json
{
  "name": "express-app",
  "version": "1.0.0",
  "description": "Sample Express application for testing",
  "main": "src/index.js",
  "scripts": {
    "start": "node src/index.js",
    "dev": "nodemon src/index.js",
    "test": "jest"
  },
  "dependencies": {
    "express": "^4.18.2",
    "mongoose": "^7.6.3",
    "cors": "^2.8.5",
    "dotenv": "^16.3.1"
  },
  "devDependencies": {
    "nodemon": "^3.0.1",
    "jest": "^29.7.0"
  }
}
```

- [ ] **Step 2: Create src/index.js**

```javascript
// tests/fixtures/express-app/src/index.js
const express = require('express');
const cors = require('cors');
const mongoose = require('mongoose');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());

// User schema
const userSchema = new mongoose.Schema({
    name: { type: String, required: true },
    email: { type: String, required: true, unique: true },
    createdAt: { type: Date, default: Date.now }
});

const User = mongoose.model('User', userSchema);

// Routes
app.get('/api/users', async (req, res) => {
    try {
        const users = await User.find();
        res.json(users);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.post('/api/users', async (req, res) => {
    try {
        const user = new User(req.body);
        await user.save();
        res.status(201).json(user);
    } catch (err) {
        res.status(400).json({ error: err.message });
    }
});

app.get('/api/users/:id', async (req, res) => {
    try {
        const user = await User.findById(req.params.id);
        if (!user) return res.status(404).json({ error: 'Not found' });
        res.json(user);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.listen(PORT, () => {
    console.log(`Server running on port ${PORT}`);
});

module.exports = app;
```

- [ ] **Step 3: Commit fixtures**

```bash
cd cast-clone-backend && git add tests/fixtures/express-app/ && git commit -m "test(fixtures): add express-app fixture with package.json and Express source"
```

---

## Task 3: Test Fixtures — Spring Pet Clinic

**Files:**
- Create: `tests/fixtures/spring-petclinic/pom.xml`
- Create: `tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/PetClinicApplication.java`
- Create: `tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/owner/OwnerController.java`
- Create: `tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/owner/OwnerRepository.java`
- Create: `tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/owner/Owner.java`
- Create: `tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/vet/VetController.java`

- [ ] **Step 1: Create pom.xml**

```xml
<!-- tests/fixtures/spring-petclinic/pom.xml -->
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
         https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>3.2.0</version>
    </parent>

    <groupId>org.springframework.samples</groupId>
    <artifactId>spring-petclinic</artifactId>
    <version>3.2.0-SNAPSHOT</version>

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
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-validation</artifactId>
        </dependency>
        <dependency>
            <groupId>org.hibernate.orm</groupId>
            <artifactId>hibernate-core</artifactId>
            <version>6.4.0.Final</version>
        </dependency>
        <dependency>
            <groupId>com.mysql</groupId>
            <artifactId>mysql-connector-j</artifactId>
            <scope>runtime</scope>
        </dependency>
        <dependency>
            <groupId>com.h2database</groupId>
            <artifactId>h2</artifactId>
            <scope>runtime</scope>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-test</artifactId>
            <scope>test</scope>
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

- [ ] **Step 3: Create Owner.java (Entity)**

```java
// tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/owner/Owner.java
package org.springframework.samples.petclinic.owner;

import jakarta.persistence.Entity;
import jakarta.persistence.Table;
import jakarta.persistence.Id;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Column;
import jakarta.persistence.OneToMany;
import jakarta.persistence.CascadeType;
import jakarta.validation.constraints.NotBlank;
import java.util.ArrayList;
import java.util.List;

@Entity
@Table(name = "owners")
public class Owner {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(name = "first_name")
    @NotBlank
    private String firstName;

    @Column(name = "last_name")
    @NotBlank
    private String lastName;

    @Column(name = "address")
    private String address;

    @Column(name = "city")
    private String city;

    @Column(name = "telephone")
    private String telephone;

    @OneToMany(cascade = CascadeType.ALL, mappedBy = "owner")
    private List<Pet> pets = new ArrayList<>();

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
    public List<Pet> getPets() { return pets; }
}
```

- [ ] **Step 4: Create OwnerController.java**

```java
// tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/owner/OwnerController.java
package org.springframework.samples.petclinic.owner;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import java.util.List;

@RestController
@RequestMapping("/api/owners")
public class OwnerController {

    @Autowired
    private OwnerRepository ownerRepository;

    @GetMapping
    public List<Owner> listOwners() {
        return ownerRepository.findAll();
    }

    @GetMapping("/{id}")
    public Owner getOwner(@PathVariable Integer id) {
        return ownerRepository.findById(id)
                .orElseThrow(() -> new RuntimeException("Owner not found"));
    }

    @GetMapping("/search")
    public List<Owner> findByLastName(String lastName) {
        return ownerRepository.findByLastName(lastName);
    }
}
```

- [ ] **Step 5: Create OwnerRepository.java**

```java
// tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/owner/OwnerRepository.java
package org.springframework.samples.petclinic.owner;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.stereotype.Repository;
import java.util.List;

@Repository
public interface OwnerRepository extends JpaRepository<Owner, Integer> {

    List<Owner> findByLastName(String lastName);

    @Query("SELECT o FROM Owner o WHERE o.city = :city")
    List<Owner> findByCity(String city);
}
```

- [ ] **Step 6: Create VetController.java**

```java
// tests/fixtures/spring-petclinic/src/main/java/org/springframework/samples/petclinic/vet/VetController.java
package org.springframework.samples.petclinic.vet;

import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.GetMapping;
import java.util.List;
import java.util.Collections;

@RestController
@RequestMapping("/api/vets")
public class VetController {

    @GetMapping
    public List<String> listVets() {
        return Collections.emptyList();
    }
}
```

- [ ] **Step 7: Commit fixtures**

```bash
cd cast-clone-backend && git add tests/fixtures/spring-petclinic/ && git commit -m "test(fixtures): add spring-petclinic fixture with multi-file Spring Boot project"
```

---

## Task 4: Stages Package Init

**Files:**
- Create: `app/stages/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create package init files**

```python
# app/stages/__init__.py
```

```python
# tests/__init__.py
```

```python
# tests/unit/__init__.py
```

- [ ] **Step 2: Create conftest.py with shared fixtures**

```python
# tests/conftest.py
"""Shared pytest fixtures for all test modules."""

from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the absolute path to tests/fixtures/."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def raw_java_dir(fixtures_dir: Path) -> Path:
    """Return the path to the raw-java fixture project."""
    return fixtures_dir / "raw-java"


@pytest.fixture
def express_app_dir(fixtures_dir: Path) -> Path:
    """Return the path to the express-app fixture project."""
    return fixtures_dir / "express-app"


@pytest.fixture
def spring_petclinic_dir(fixtures_dir: Path) -> Path:
    """Return the path to the spring-petclinic fixture project."""
    return fixtures_dir / "spring-petclinic"
```

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend && git add app/stages/__init__.py tests/__init__.py tests/unit/__init__.py tests/conftest.py && git commit -m "chore: add stages package and test infrastructure with shared fixtures"
```

---

## Task 5: Project Discovery — Tests

**Files:**
- Create: `tests/unit/test_discovery.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_discovery.py
"""Tests for Stage 1: Project Discovery."""

from pathlib import Path

import pytest

from app.models.enums import Confidence
from app.models.manifest import (
    BuildTool,
    DetectedFramework,
    DetectedLanguage,
    ProjectManifest,
    SourceFile,
)
from app.stages.discovery import (
    EXTENSION_LANGUAGE_MAP,
    SKIP_DIRS,
    count_loc,
    detect_build_tools,
    detect_frameworks,
    detect_language,
    discover_project,
    walk_source_files,
)


# ── Language Detection ────────────────────────────────────────────


class TestDetectLanguage:
    def test_java_extension(self):
        assert detect_language(Path("Foo.java")) == "java"

    def test_python_extension(self):
        assert detect_language(Path("main.py")) == "python"

    def test_typescript_extension(self):
        assert detect_language(Path("app.ts")) == "typescript"

    def test_tsx_extension(self):
        assert detect_language(Path("Component.tsx")) == "typescript"

    def test_javascript_extension(self):
        assert detect_language(Path("index.js")) == "javascript"

    def test_jsx_extension(self):
        assert detect_language(Path("App.jsx")) == "javascript"

    def test_csharp_extension(self):
        assert detect_language(Path("Program.cs")) == "csharp"

    def test_sql_extension(self):
        assert detect_language(Path("migration.sql")) == "sql"

    def test_unknown_extension_returns_none(self):
        assert detect_language(Path("README.md")) is None

    def test_no_extension_returns_none(self):
        assert detect_language(Path("Makefile")) is None


# ── LOC Counting ─────────────────────────────────────────────────


class TestCountLoc:
    def test_counts_non_empty_lines(self, tmp_path: Path):
        f = tmp_path / "test.java"
        f.write_text("public class Foo {\n    int x = 1;\n}\n")
        assert count_loc(f) == 3

    def test_skips_empty_lines(self, tmp_path: Path):
        f = tmp_path / "test.java"
        f.write_text("line1\n\n\nline2\n")
        assert count_loc(f) == 2

    def test_skips_whitespace_only_lines(self, tmp_path: Path):
        f = tmp_path / "test.java"
        f.write_text("line1\n   \n\t\nline2\n")
        assert count_loc(f) == 2

    def test_skips_double_slash_comments(self, tmp_path: Path):
        f = tmp_path / "test.java"
        f.write_text("// this is a comment\nint x = 1;\n// another comment\n")
        assert count_loc(f) == 1

    def test_skips_hash_comments(self, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("# comment\nx = 1\n# another\ny = 2\n")
        assert count_loc(f) == 2

    def test_skips_block_comment_markers(self, tmp_path: Path):
        f = tmp_path / "test.java"
        f.write_text("/*\n * block comment\n */\nint x = 1;\n")
        assert count_loc(f) == 1

    def test_skips_sql_dash_comments(self, tmp_path: Path):
        f = tmp_path / "test.sql"
        f.write_text("-- comment\nSELECT * FROM users;\n-- end\n")
        assert count_loc(f) == 1

    def test_empty_file_returns_zero(self, tmp_path: Path):
        f = tmp_path / "empty.java"
        f.write_text("")
        assert count_loc(f) == 0

    def test_binary_file_returns_zero(self, tmp_path: Path):
        f = tmp_path / "binary.java"
        f.write_bytes(b"\x00\x01\x02\xff\xfe")
        assert count_loc(f) == 0


# ── Filesystem Walk ──────────────────────────────────────────────


class TestWalkSourceFiles:
    def test_finds_java_files(self, raw_java_dir: Path):
        files = walk_source_files(raw_java_dir)
        java_files = [f for f in files if f.language == "java"]
        assert len(java_files) == 2  # UserService.java, UserController.java

    def test_skips_hidden_dirs(self, tmp_path: Path):
        hidden = tmp_path / ".git" / "objects"
        hidden.mkdir(parents=True)
        (hidden / "Foo.java").write_text("class Foo {}")
        normal = tmp_path / "src"
        normal.mkdir()
        (normal / "Bar.java").write_text("class Bar {}")
        files = walk_source_files(tmp_path)
        assert len(files) == 1
        assert files[0].path == "src/Bar.java"

    def test_skips_build_output_dirs(self, tmp_path: Path):
        for skip_dir in ["node_modules", "target", "build", "__pycache__"]:
            d = tmp_path / skip_dir
            d.mkdir()
            (d / "Foo.java").write_text("class Foo {}")
        src = tmp_path / "src"
        src.mkdir()
        (src / "Main.java").write_text("class Main {}")
        files = walk_source_files(tmp_path)
        assert len(files) == 1

    def test_returns_relative_paths(self, raw_java_dir: Path):
        files = walk_source_files(raw_java_dir)
        for f in files:
            assert not Path(f.path).is_absolute()
            assert f.path.startswith("src/")

    def test_includes_size_bytes(self, raw_java_dir: Path):
        files = walk_source_files(raw_java_dir)
        for f in files:
            assert f.size_bytes > 0

    def test_ignores_unknown_extensions(self, tmp_path: Path):
        (tmp_path / "readme.md").write_text("# Hello")
        (tmp_path / "Main.java").write_text("class Main {}")
        files = walk_source_files(tmp_path)
        assert len(files) == 1
        assert files[0].language == "java"


# ── Build Tool Detection ─────────────────────────────────────────


class TestDetectBuildTools:
    def test_detects_maven(self, raw_java_dir: Path):
        tools = detect_build_tools(raw_java_dir)
        maven_tools = [t for t in tools if t.name == "maven"]
        assert len(maven_tools) == 1
        assert maven_tools[0].config_file == "pom.xml"
        assert maven_tools[0].language == "java"

    def test_detects_npm(self, express_app_dir: Path):
        tools = detect_build_tools(express_app_dir)
        npm_tools = [t for t in tools if t.name == "npm"]
        assert len(npm_tools) == 1
        assert npm_tools[0].config_file == "package.json"

    def test_detects_gradle(self, tmp_path: Path):
        (tmp_path / "build.gradle").write_text("apply plugin: 'java'")
        tools = detect_build_tools(tmp_path)
        assert any(t.name == "gradle" for t in tools)

    def test_detects_gradle_kts(self, tmp_path: Path):
        (tmp_path / "build.gradle.kts").write_text("plugins { java }")
        tools = detect_build_tools(tmp_path)
        assert any(t.name == "gradle" for t in tools)

    def test_detects_pyproject(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "myapp"\n')
        tools = detect_build_tools(tmp_path)
        assert any(t.name == "uv/pip" for t in tools)

    def test_detects_requirements_txt(self, tmp_path: Path):
        (tmp_path / "requirements.txt").write_text("flask==3.0.0\n")
        tools = detect_build_tools(tmp_path)
        assert any(t.name == "pip" for t in tools)

    def test_detects_setup_py(self, tmp_path: Path):
        (tmp_path / "setup.py").write_text("from setuptools import setup\nsetup()")
        tools = detect_build_tools(tmp_path)
        assert any(t.name == "pip" for t in tools)

    def test_detects_dotnet_csproj(self, tmp_path: Path):
        (tmp_path / "MyApp.csproj").write_text("<Project></Project>")
        tools = detect_build_tools(tmp_path)
        assert any(t.name == "dotnet" for t in tools)

    def test_detects_dotnet_sln(self, tmp_path: Path):
        (tmp_path / "MyApp.sln").write_text("Microsoft Visual Studio Solution")
        tools = detect_build_tools(tmp_path)
        assert any(t.name == "dotnet" for t in tools)

    def test_empty_dir_returns_empty(self, tmp_path: Path):
        tools = detect_build_tools(tmp_path)
        assert tools == []


# ── Framework Detection ──────────────────────────────────────────


class TestDetectFrameworks:
    def test_detects_spring_boot_from_pom(self, raw_java_dir: Path):
        tools = detect_build_tools(raw_java_dir)
        frameworks = detect_frameworks(raw_java_dir, tools)
        spring = [f for f in frameworks if f.name == "spring-boot"]
        assert len(spring) == 1
        assert spring[0].confidence == Confidence.HIGH
        assert spring[0].language == "java"

    def test_detects_hibernate_from_pom(self, raw_java_dir: Path):
        tools = detect_build_tools(raw_java_dir)
        frameworks = detect_frameworks(raw_java_dir, tools)
        hibernate = [f for f in frameworks if f.name == "hibernate"]
        assert len(hibernate) == 1
        assert hibernate[0].confidence == Confidence.HIGH

    def test_detects_spring_data_jpa(self, raw_java_dir: Path):
        tools = detect_build_tools(raw_java_dir)
        frameworks = detect_frameworks(raw_java_dir, tools)
        jpa = [f for f in frameworks if f.name == "spring-data-jpa"]
        assert len(jpa) == 1

    def test_detects_express_from_package_json(self, express_app_dir: Path):
        tools = detect_build_tools(express_app_dir)
        frameworks = detect_frameworks(express_app_dir, tools)
        express = [f for f in frameworks if f.name == "express"]
        assert len(express) == 1
        assert express[0].confidence == Confidence.HIGH
        assert express[0].language == "javascript"

    def test_detects_react_from_package_json(self, tmp_path: Path):
        pkg = tmp_path / "package.json"
        pkg.write_text('{"dependencies": {"react": "^18.2.0"}}')
        tools = detect_build_tools(tmp_path)
        frameworks = detect_frameworks(tmp_path, tools)
        react = [f for f in frameworks if f.name == "react"]
        assert len(react) == 1

    def test_detects_nestjs(self, tmp_path: Path):
        pkg = tmp_path / "package.json"
        pkg.write_text('{"dependencies": {"@nestjs/core": "^10.0.0"}}')
        tools = detect_build_tools(tmp_path)
        frameworks = detect_frameworks(tmp_path, tools)
        nest = [f for f in frameworks if f.name == "nestjs"]
        assert len(nest) == 1

    def test_detects_angular(self, tmp_path: Path):
        pkg = tmp_path / "package.json"
        pkg.write_text('{"dependencies": {"@angular/core": "^17.0.0"}}')
        tools = detect_build_tools(tmp_path)
        frameworks = detect_frameworks(tmp_path, tools)
        angular = [f for f in frameworks if f.name == "angular"]
        assert len(angular) == 1

    def test_detects_django_from_requirements(self, tmp_path: Path):
        req = tmp_path / "requirements.txt"
        req.write_text("django==5.0\ncelery==5.3.4\n")
        tools = detect_build_tools(tmp_path)
        frameworks = detect_frameworks(tmp_path, tools)
        django = [f for f in frameworks if f.name == "django"]
        assert len(django) == 1
        assert django[0].language == "python"

    def test_detects_fastapi_from_pyproject(self, tmp_path: Path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text(
            '[project]\nname = "myapp"\ndependencies = ["fastapi>=0.104.0", "uvicorn"]\n'
        )
        tools = detect_build_tools(tmp_path)
        frameworks = detect_frameworks(tmp_path, tools)
        fastapi = [f for f in frameworks if f.name == "fastapi"]
        assert len(fastapi) == 1

    def test_detects_aspnet_from_csproj(self, tmp_path: Path):
        csproj = tmp_path / "MyApp.csproj"
        csproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk.Web">\n'
            "  <ItemGroup>\n"
            '    <PackageReference Include="Microsoft.AspNetCore.OpenApi" />\n'
            "  </ItemGroup>\n"
            "</Project>\n"
        )
        tools = detect_build_tools(tmp_path)
        frameworks = detect_frameworks(tmp_path, tools)
        aspnet = [f for f in frameworks if f.name == "aspnet"]
        assert len(aspnet) == 1
        assert aspnet[0].language == "csharp"

    def test_no_frameworks_in_empty_project(self, tmp_path: Path):
        frameworks = detect_frameworks(tmp_path, [])
        assert frameworks == []


# ── Full Discovery Integration ───────────────────────────────────


class TestDiscoverProject:
    def test_discovers_raw_java(self, raw_java_dir: Path):
        manifest = discover_project(raw_java_dir)
        assert isinstance(manifest, ProjectManifest)
        assert manifest.root_path == raw_java_dir
        assert manifest.total_files == 2
        assert manifest.total_loc > 0
        assert manifest.has_language("java")
        assert len(manifest.build_tools) == 1
        assert manifest.build_tools[0].name == "maven"

    def test_discovers_express_app(self, express_app_dir: Path):
        manifest = discover_project(express_app_dir)
        assert manifest.total_files == 1  # Only .js file, not package.json
        assert manifest.has_language("javascript")
        assert any(f.name == "express" for f in manifest.detected_frameworks)

    def test_discovers_spring_petclinic(self, spring_petclinic_dir: Path):
        manifest = discover_project(spring_petclinic_dir)
        assert manifest.total_files == 5  # 5 Java files
        assert manifest.has_language("java")
        # Should detect spring-boot and hibernate
        framework_names = [f.name for f in manifest.detected_frameworks]
        assert "spring-boot" in framework_names
        assert "hibernate" in framework_names

    def test_language_stats_are_aggregated(self, spring_petclinic_dir: Path):
        manifest = discover_project(spring_petclinic_dir)
        java_lang = [l for l in manifest.detected_languages if l.name == "java"][0]
        assert java_lang.file_count == 5
        assert java_lang.total_loc > 0

    def test_manifest_total_loc_matches_sum(self, raw_java_dir: Path):
        manifest = discover_project(raw_java_dir)
        lang_loc_sum = sum(l.total_loc for l in manifest.detected_languages)
        assert manifest.total_loc == lang_loc_sum

    def test_empty_directory(self, tmp_path: Path):
        manifest = discover_project(tmp_path)
        assert manifest.total_files == 0
        assert manifest.total_loc == 0
        assert manifest.detected_languages == []
        assert manifest.detected_frameworks == []
        assert manifest.build_tools == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_discovery.py -v`
Expected: FAIL (ImportError — `app.stages.discovery` does not exist)

- [ ] **Step 3: Commit test file**

```bash
cd cast-clone-backend && git add tests/unit/test_discovery.py && git commit -m "test(discovery): add failing tests for Stage 1 project discovery"
```

---

## Task 6: Project Discovery — Implementation

**Files:**
- Create: `app/stages/discovery.py`

- [ ] **Step 1: Implement discover_project()**

```python
# app/stages/discovery.py
"""Stage 1: Project Discovery.

Walks a source directory, identifies languages, build tools, and frameworks.
Produces a ProjectManifest used by all subsequent pipeline stages.

This is a SYNCHRONOUS function — filesystem I/O is fast and does not benefit
from async. It is the only critical stage (failure = abort pipeline).
"""

from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import structlog

from app.models.enums import Confidence
from app.models.manifest import (
    BuildTool,
    DetectedFramework,
    DetectedLanguage,
    ProjectManifest,
    SourceFile,
)

logger = structlog.get_logger(__name__)

# ── Constants ────────────────────────────────────────────────────

EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".java": "java",
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".cs": "csharp",
    ".sql": "sql",
}

SKIP_DIRS: set[str] = {
    # Hidden dirs
    ".git",
    ".svn",
    ".hg",
    ".idea",
    ".vscode",
    ".settings",
    ".classpath",
    ".project",
    # Build output
    "node_modules",
    "target",
    "build",
    "dist",
    "bin",
    "obj",
    "__pycache__",
    ".gradle",
    ".mvn",
    # Vendor
    "vendor",
    # Python virtual envs
    ".venv",
    "venv",
    ".tox",
    # .NET
    "packages",
}

# Lines starting with these prefixes (after stripping) are comments
_COMMENT_PREFIXES = ("//", "#", "/*", "*", "*/", "--")


# ── Public API ───────────────────────────────────────────────────


def discover_project(source_path: Path) -> ProjectManifest:
    """Stage 1 entry point: scan filesystem and build a ProjectManifest.

    Args:
        source_path: Absolute path to the root of the codebase to analyze.

    Returns:
        A ProjectManifest with all detected files, languages, frameworks,
        and build tools.

    Raises:
        FileNotFoundError: If source_path does not exist.
        NotADirectoryError: If source_path is not a directory.
    """
    start = time.monotonic()
    log = logger.bind(source_path=str(source_path))
    log.info("discovery.start", stage="discovery")

    if not source_path.exists():
        raise FileNotFoundError(f"Source path does not exist: {source_path}")
    if not source_path.is_dir():
        raise NotADirectoryError(f"Source path is not a directory: {source_path}")

    # Step 1: Walk filesystem, detect language per file, count LOC
    source_files = walk_source_files(source_path)

    # Step 2: Aggregate language stats
    lang_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"file_count": 0, "total_loc": 0}
    )
    for sf in source_files:
        lang_stats[sf.language]["file_count"] += 1
        # Count LOC for each file
        full_path = source_path / sf.path
        loc = count_loc(full_path)
        lang_stats[sf.language]["total_loc"] += loc

    detected_languages = [
        DetectedLanguage(
            name=lang_name,
            file_count=stats["file_count"],
            total_loc=stats["total_loc"],
        )
        for lang_name, stats in sorted(
            lang_stats.items(), key=lambda x: x[1]["file_count"], reverse=True
        )
    ]

    total_files = len(source_files)
    total_loc = sum(lang.total_loc for lang in detected_languages)

    # Step 3: Detect build tools
    build_tools = detect_build_tools(source_path)

    # Step 4: Detect frameworks
    detected_frameworks = detect_frameworks(source_path, build_tools)

    manifest = ProjectManifest(
        root_path=source_path,
        source_files=source_files,
        detected_languages=detected_languages,
        detected_frameworks=detected_frameworks,
        build_tools=build_tools,
        total_files=total_files,
        total_loc=total_loc,
    )

    elapsed = time.monotonic() - start
    log.info(
        "discovery.complete",
        stage="discovery",
        total_files=total_files,
        total_loc=total_loc,
        languages=[l.name for l in detected_languages],
        frameworks=[f.name for f in detected_frameworks],
        build_tools=[t.name for t in build_tools],
        elapsed_seconds=round(elapsed, 3),
    )

    return manifest


# ── File Walking ─────────────────────────────────────────────────


def walk_source_files(root: Path) -> list[SourceFile]:
    """Recursively walk root, returning SourceFile for each recognized source file.

    Skips hidden directories, build output directories, and vendor directories
    as defined in SKIP_DIRS. Only includes files with extensions in
    EXTENSION_LANGUAGE_MAP.

    Args:
        root: The root directory to walk.

    Returns:
        List of SourceFile with relative paths, detected language, and size.
    """
    source_files: list[SourceFile] = []

    for path in _walk_filtered(root):
        language = detect_language(path)
        if language is not None:
            relative = path.relative_to(root)
            source_files.append(
                SourceFile(
                    path=str(relative),
                    language=language,
                    size_bytes=path.stat().st_size,
                )
            )

    return source_files


def _walk_filtered(root: Path) -> list[Path]:
    """Walk directory tree, skipping SKIP_DIRS. Returns list of file Paths."""
    result: list[Path] = []

    def _recurse(directory: Path) -> None:
        try:
            entries = sorted(directory.iterdir())
        except PermissionError:
            logger.warning("discovery.permission_denied", path=str(directory))
            return

        for entry in entries:
            if entry.is_dir():
                if entry.name not in SKIP_DIRS and not entry.name.startswith("."):
                    _recurse(entry)
            elif entry.is_file():
                result.append(entry)

    _recurse(root)
    return result


# ── Language Detection ───────────────────────────────────────────


def detect_language(path: Path) -> str | None:
    """Detect programming language from file extension.

    Args:
        path: Path to a source file (can be relative or absolute).

    Returns:
        Language name string (e.g., "java", "python") or None if unrecognized.
    """
    suffix = path.suffix.lower()
    return EXTENSION_LANGUAGE_MAP.get(suffix)


# ── LOC Counting ─────────────────────────────────────────────────


def count_loc(file_path: Path) -> int:
    """Count non-empty, non-comment lines in a source file.

    Simple heuristic: strip whitespace, skip empty lines and lines starting
    with common comment prefixes (//, #, /*, *, --)

    Args:
        file_path: Absolute path to the source file.

    Returns:
        Number of lines of code (LOC). Returns 0 for binary or unreadable files.
    """
    try:
        text = file_path.read_text(encoding="utf-8", errors="strict")
    except (UnicodeDecodeError, OSError):
        return 0

    count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(_COMMENT_PREFIXES):
            continue
        count += 1

    return count


# ── Build Tool Detection ─────────────────────────────────────────


def detect_build_tools(root: Path) -> list[BuildTool]:
    """Detect build tools by looking for known build configuration files.

    Args:
        root: The root directory of the project.

    Returns:
        List of detected BuildTool instances.
    """
    tools: list[BuildTool] = []

    # Maven
    if (root / "pom.xml").is_file():
        tools.append(BuildTool(name="maven", config_file="pom.xml", language="java"))

    # Gradle
    if (root / "build.gradle").is_file():
        tools.append(
            BuildTool(name="gradle", config_file="build.gradle", language="java")
        )
    elif (root / "build.gradle.kts").is_file():
        tools.append(
            BuildTool(
                name="gradle", config_file="build.gradle.kts", language="java"
            )
        )

    # npm
    if (root / "package.json").is_file():
        tools.append(
            BuildTool(name="npm", config_file="package.json", language="javascript")
        )

    # Python — pyproject.toml (uv/pip)
    if (root / "pyproject.toml").is_file():
        tools.append(
            BuildTool(
                name="uv/pip", config_file="pyproject.toml", language="python"
            )
        )
    elif (root / "setup.py").is_file():
        tools.append(
            BuildTool(name="pip", config_file="setup.py", language="python")
        )
    elif (root / "requirements.txt").is_file():
        tools.append(
            BuildTool(
                name="pip", config_file="requirements.txt", language="python"
            )
        )

    # .NET — .csproj or .sln
    csproj_files = list(root.glob("*.csproj"))
    sln_files = list(root.glob("*.sln"))
    if csproj_files:
        tools.append(
            BuildTool(
                name="dotnet",
                config_file=csproj_files[0].name,
                language="csharp",
            )
        )
    elif sln_files:
        tools.append(
            BuildTool(
                name="dotnet", config_file=sln_files[0].name, language="csharp"
            )
        )

    return tools


# ── Framework Detection ──────────────────────────────────────────


def detect_frameworks(
    root: Path, build_tools: list[BuildTool]
) -> list[DetectedFramework]:
    """Detect frameworks by scanning build configuration files for known dependencies.

    Args:
        root: The root directory of the project.
        build_tools: Previously detected build tools (from detect_build_tools).

    Returns:
        List of detected frameworks with confidence levels and evidence.
    """
    frameworks: list[DetectedFramework] = []

    for tool in build_tools:
        config_path = root / tool.config_file
        if not config_path.is_file():
            continue

        if tool.name == "maven":
            frameworks.extend(_detect_frameworks_maven(config_path))
        elif tool.name == "gradle":
            frameworks.extend(_detect_frameworks_gradle(config_path))
        elif tool.name == "npm":
            frameworks.extend(_detect_frameworks_npm(config_path))
        elif tool.name in ("uv/pip", "pip"):
            frameworks.extend(_detect_frameworks_python(config_path, tool.config_file))
        elif tool.name == "dotnet":
            frameworks.extend(_detect_frameworks_dotnet(config_path))

    return frameworks


def _detect_frameworks_maven(pom_path: Path) -> list[DetectedFramework]:
    """Detect Java frameworks from pom.xml."""
    frameworks: list[DetectedFramework] = []

    try:
        content = pom_path.read_text(encoding="utf-8")
    except OSError:
        return frameworks

    # Spring Boot
    if "spring-boot" in content:
        frameworks.append(
            DetectedFramework(
                name="spring-boot",
                language="java",
                confidence=Confidence.HIGH,
                evidence=["pom.xml contains spring-boot dependency"],
            )
        )

    # Hibernate
    if "hibernate" in content.lower():
        frameworks.append(
            DetectedFramework(
                name="hibernate",
                language="java",
                confidence=Confidence.HIGH,
                evidence=["pom.xml contains hibernate dependency"],
            )
        )

    # Spring Data JPA
    if "spring-data-jpa" in content or "spring-boot-starter-data-jpa" in content:
        frameworks.append(
            DetectedFramework(
                name="spring-data-jpa",
                language="java",
                confidence=Confidence.HIGH,
                evidence=["pom.xml contains spring-data-jpa dependency"],
            )
        )

    return frameworks


def _detect_frameworks_gradle(gradle_path: Path) -> list[DetectedFramework]:
    """Detect Java frameworks from build.gradle or build.gradle.kts."""
    frameworks: list[DetectedFramework] = []

    try:
        content = gradle_path.read_text(encoding="utf-8")
    except OSError:
        return frameworks

    if "spring-boot" in content:
        frameworks.append(
            DetectedFramework(
                name="spring-boot",
                language="java",
                confidence=Confidence.HIGH,
                evidence=[f"{gradle_path.name} contains spring-boot"],
            )
        )

    if "hibernate" in content.lower():
        frameworks.append(
            DetectedFramework(
                name="hibernate",
                language="java",
                confidence=Confidence.HIGH,
                evidence=[f"{gradle_path.name} contains hibernate"],
            )
        )

    if "spring-data-jpa" in content:
        frameworks.append(
            DetectedFramework(
                name="spring-data-jpa",
                language="java",
                confidence=Confidence.HIGH,
                evidence=[f"{gradle_path.name} contains spring-data-jpa"],
            )
        )

    return frameworks


def _detect_frameworks_npm(package_json_path: Path) -> list[DetectedFramework]:
    """Detect JS/TS frameworks from package.json."""
    frameworks: list[DetectedFramework] = []

    try:
        data = json.loads(package_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return frameworks

    all_deps: dict[str, str] = {}
    all_deps.update(data.get("dependencies", {}))
    all_deps.update(data.get("devDependencies", {}))

    # Express
    if "express" in all_deps:
        frameworks.append(
            DetectedFramework(
                name="express",
                language="javascript",
                confidence=Confidence.HIGH,
                evidence=["package.json has express dependency"],
            )
        )

    # React
    if "react" in all_deps:
        frameworks.append(
            DetectedFramework(
                name="react",
                language="javascript",
                confidence=Confidence.HIGH,
                evidence=["package.json has react dependency"],
            )
        )

    # NestJS
    if "@nestjs/core" in all_deps:
        frameworks.append(
            DetectedFramework(
                name="nestjs",
                language="typescript",
                confidence=Confidence.HIGH,
                evidence=["package.json has @nestjs/core dependency"],
            )
        )

    # Angular
    if "@angular/core" in all_deps:
        frameworks.append(
            DetectedFramework(
                name="angular",
                language="typescript",
                confidence=Confidence.HIGH,
                evidence=["package.json has @angular/core dependency"],
            )
        )

    return frameworks


def _detect_frameworks_python(
    config_path: Path, config_file: str
) -> list[DetectedFramework]:
    """Detect Python frameworks from pyproject.toml or requirements.txt."""
    frameworks: list[DetectedFramework] = []

    try:
        content = config_path.read_text(encoding="utf-8")
    except OSError:
        return frameworks

    content_lower = content.lower()

    # Django
    if "django" in content_lower:
        # Avoid false positive on django-rest-framework matching without django
        # "django" will match "django==5.0", "Django>=4.0", etc.
        frameworks.append(
            DetectedFramework(
                name="django",
                language="python",
                confidence=Confidence.HIGH,
                evidence=[f"{config_file} contains django dependency"],
            )
        )

    # FastAPI
    if "fastapi" in content_lower:
        frameworks.append(
            DetectedFramework(
                name="fastapi",
                language="python",
                confidence=Confidence.HIGH,
                evidence=[f"{config_file} contains fastapi dependency"],
            )
        )

    return frameworks


def _detect_frameworks_dotnet(csproj_path: Path) -> list[DetectedFramework]:
    """Detect .NET frameworks from .csproj files."""
    frameworks: list[DetectedFramework] = []

    try:
        content = csproj_path.read_text(encoding="utf-8")
    except OSError:
        return frameworks

    if "Microsoft.AspNetCore" in content or 'Sdk="Microsoft.NET.Sdk.Web"' in content:
        frameworks.append(
            DetectedFramework(
                name="aspnet",
                language="csharp",
                confidence=Confidence.HIGH,
                evidence=[f"{csproj_path.name} contains ASP.NET Core reference"],
            )
        )

    return frameworks
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_discovery.py -v`
Expected: PASS (all tests green)

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend && git add app/stages/discovery.py && git commit -m "feat(stages): implement Stage 1 project discovery with language, build tool, and framework detection"
```

---

## Task 7: Dependency Resolution — Tests

**Files:**
- Create: `tests/unit/test_dependencies.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_dependencies.py
"""Tests for Stage 2: Dependency Resolution."""

from pathlib import Path

import pytest

from app.models.manifest import (
    BuildTool,
    ProjectManifest,
    ResolvedDependency,
    ResolvedEnvironment,
)
from app.stages.dependencies import (
    parse_maven_dependencies,
    parse_npm_dependencies,
    parse_python_dependencies,
    parse_dotnet_dependencies,
    resolve_dependencies,
)


# ── Maven Dependency Parsing ─────────────────────────────────────


class TestParseMavenDependencies:
    def test_extracts_dependencies(self, raw_java_dir: Path):
        deps = parse_maven_dependencies(raw_java_dir / "pom.xml")
        assert len(deps) > 0

    def test_extracts_group_and_artifact(self, raw_java_dir: Path):
        deps = parse_maven_dependencies(raw_java_dir / "pom.xml")
        dep_names = [d.name for d in deps]
        assert "org.springframework.boot:spring-boot-starter-web" in dep_names

    def test_extracts_version_when_present(self, raw_java_dir: Path):
        deps = parse_maven_dependencies(raw_java_dir / "pom.xml")
        hibernate = [d for d in deps if "hibernate" in d.name]
        assert len(hibernate) == 1
        assert hibernate[0].version == "6.4.0.Final"

    def test_version_is_none_when_managed(self, raw_java_dir: Path):
        deps = parse_maven_dependencies(raw_java_dir / "pom.xml")
        starter_web = [d for d in deps if "starter-web" in d.name]
        assert len(starter_web) == 1
        assert starter_web[0].version is None

    def test_extracts_scope(self, raw_java_dir: Path):
        deps = parse_maven_dependencies(raw_java_dir / "pom.xml")
        h2 = [d for d in deps if "h2" in d.name]
        assert len(h2) == 1
        assert h2[0].scope == "runtime"

    def test_default_scope_is_compile(self, raw_java_dir: Path):
        deps = parse_maven_dependencies(raw_java_dir / "pom.xml")
        starter_web = [d for d in deps if "starter-web" in d.name]
        assert starter_web[0].scope == "compile"

    def test_test_scope(self, raw_java_dir: Path):
        deps = parse_maven_dependencies(raw_java_dir / "pom.xml")
        test_deps = [d for d in deps if d.scope == "test"]
        assert len(test_deps) >= 1

    def test_nonexistent_file_returns_empty(self, tmp_path: Path):
        deps = parse_maven_dependencies(tmp_path / "nonexistent.xml")
        assert deps == []

    def test_malformed_xml_returns_empty(self, tmp_path: Path):
        bad = tmp_path / "pom.xml"
        bad.write_text("this is not xml")
        deps = parse_maven_dependencies(bad)
        assert deps == []


# ── npm Dependency Parsing ───────────────────────────────────────


class TestParseNpmDependencies:
    def test_extracts_dependencies(self, express_app_dir: Path):
        deps = parse_npm_dependencies(express_app_dir / "package.json")
        assert len(deps) > 0

    def test_extracts_name_and_version(self, express_app_dir: Path):
        deps = parse_npm_dependencies(express_app_dir / "package.json")
        express = [d for d in deps if d.name == "express"]
        assert len(express) == 1
        assert express[0].version == "^4.18.2"

    def test_includes_dev_dependencies(self, express_app_dir: Path):
        deps = parse_npm_dependencies(express_app_dir / "package.json")
        dev_deps = [d for d in deps if d.scope == "dev"]
        assert len(dev_deps) >= 1
        assert any(d.name == "jest" for d in dev_deps)

    def test_production_scope_for_deps(self, express_app_dir: Path):
        deps = parse_npm_dependencies(express_app_dir / "package.json")
        express = [d for d in deps if d.name == "express"]
        assert express[0].scope == "compile"

    def test_nonexistent_file_returns_empty(self, tmp_path: Path):
        deps = parse_npm_dependencies(tmp_path / "nope.json")
        assert deps == []

    def test_malformed_json_returns_empty(self, tmp_path: Path):
        bad = tmp_path / "package.json"
        bad.write_text("{invalid json")
        deps = parse_npm_dependencies(bad)
        assert deps == []


# ── Python Dependency Parsing ────────────────────────────────────


class TestParsePythonDependencies:
    def test_parses_requirements_txt(self, tmp_path: Path):
        req = tmp_path / "requirements.txt"
        req.write_text("flask==3.0.0\nrequests>=2.31.0\nnumpy\n")
        deps = parse_python_dependencies(req)
        assert len(deps) == 3

    def test_extracts_version_from_requirements(self, tmp_path: Path):
        req = tmp_path / "requirements.txt"
        req.write_text("flask==3.0.0\n")
        deps = parse_python_dependencies(req)
        assert deps[0].name == "flask"
        assert deps[0].version == "3.0.0"

    def test_extracts_version_with_gte(self, tmp_path: Path):
        req = tmp_path / "requirements.txt"
        req.write_text("requests>=2.31.0\n")
        deps = parse_python_dependencies(req)
        assert deps[0].name == "requests"
        assert deps[0].version == ">=2.31.0"

    def test_no_version_gives_none(self, tmp_path: Path):
        req = tmp_path / "requirements.txt"
        req.write_text("numpy\n")
        deps = parse_python_dependencies(req)
        assert deps[0].name == "numpy"
        assert deps[0].version is None

    def test_skips_comments_and_blanks(self, tmp_path: Path):
        req = tmp_path / "requirements.txt"
        req.write_text("# comment\n\nflask==3.0.0\n  \n")
        deps = parse_python_dependencies(req)
        assert len(deps) == 1

    def test_skips_option_lines(self, tmp_path: Path):
        req = tmp_path / "requirements.txt"
        req.write_text("-r other.txt\n--index-url https://pypi.org\nflask\n")
        deps = parse_python_dependencies(req)
        assert len(deps) == 1

    def test_parses_pyproject_toml(self, tmp_path: Path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text(
            '[project]\nname = "myapp"\ndependencies = [\n'
            '    "fastapi>=0.104.0",\n'
            '    "uvicorn[standard]",\n'
            '    "pydantic>=2.0",\n'
            "]\n"
        )
        deps = parse_python_dependencies(toml)
        assert len(deps) == 3
        fastapi = [d for d in deps if d.name == "fastapi"]
        assert len(fastapi) == 1
        assert fastapi[0].version == ">=0.104.0"

    def test_pyproject_with_extras_strips_extras(self, tmp_path: Path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text(
            '[project]\nname = "x"\ndependencies = ["uvicorn[standard]>=0.24.0"]\n'
        )
        deps = parse_python_dependencies(toml)
        assert deps[0].name == "uvicorn"

    def test_nonexistent_file_returns_empty(self, tmp_path: Path):
        deps = parse_python_dependencies(tmp_path / "nope.txt")
        assert deps == []


# ── .NET Dependency Parsing ──────────────────────────────────────


class TestParseDotnetDependencies:
    def test_extracts_package_references(self, tmp_path: Path):
        csproj = tmp_path / "MyApp.csproj"
        csproj.write_text(
            "<Project>\n"
            "  <ItemGroup>\n"
            '    <PackageReference Include="Newtonsoft.Json" Version="13.0.3" />\n'
            '    <PackageReference Include="Serilog" Version="3.1.1" />\n'
            "  </ItemGroup>\n"
            "</Project>\n"
        )
        deps = parse_dotnet_dependencies(csproj)
        assert len(deps) == 2
        json_dep = [d for d in deps if d.name == "Newtonsoft.Json"]
        assert len(json_dep) == 1
        assert json_dep[0].version == "13.0.3"

    def test_handles_no_version_attribute(self, tmp_path: Path):
        csproj = tmp_path / "MyApp.csproj"
        csproj.write_text(
            "<Project>\n"
            "  <ItemGroup>\n"
            '    <PackageReference Include="SomePackage" />\n'
            "  </ItemGroup>\n"
            "</Project>\n"
        )
        deps = parse_dotnet_dependencies(csproj)
        assert len(deps) == 1
        assert deps[0].version is None

    def test_nonexistent_file_returns_empty(self, tmp_path: Path):
        deps = parse_dotnet_dependencies(tmp_path / "nope.csproj")
        assert deps == []


# ── Full Resolve Dependencies Integration ────────────────────────


class TestResolveDependencies:
    @pytest.mark.asyncio
    async def test_resolves_maven_project(self, raw_java_dir: Path):
        manifest = ProjectManifest(
            root_path=raw_java_dir,
            build_tools=[
                BuildTool(name="maven", config_file="pom.xml", language="java")
            ],
        )
        env = await resolve_dependencies(manifest)
        assert isinstance(env, ResolvedEnvironment)
        assert "java" in env.dependencies
        assert len(env.dependencies["java"]) > 0

    @pytest.mark.asyncio
    async def test_resolves_npm_project(self, express_app_dir: Path):
        manifest = ProjectManifest(
            root_path=express_app_dir,
            build_tools=[
                BuildTool(
                    name="npm",
                    config_file="package.json",
                    language="javascript",
                )
            ],
        )
        env = await resolve_dependencies(manifest)
        assert "javascript" in env.dependencies
        assert any(d.name == "express" for d in env.dependencies["javascript"])

    @pytest.mark.asyncio
    async def test_empty_manifest_returns_empty_env(self, tmp_path: Path):
        manifest = ProjectManifest(root_path=tmp_path)
        env = await resolve_dependencies(manifest)
        assert env.dependencies == {}
        assert env.errors == []

    @pytest.mark.asyncio
    async def test_missing_config_records_error(self, tmp_path: Path):
        manifest = ProjectManifest(
            root_path=tmp_path,
            build_tools=[
                BuildTool(name="maven", config_file="pom.xml", language="java")
            ],
        )
        env = await resolve_dependencies(manifest)
        # No pom.xml at tmp_path, so java deps should be empty
        assert env.dependencies.get("java", []) == []

    @pytest.mark.asyncio
    async def test_multiple_build_tools(self, tmp_path: Path):
        # Create both pom.xml and package.json
        pom = tmp_path / "pom.xml"
        pom.write_text(
            '<?xml version="1.0"?>\n'
            '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
            "  <dependencies>\n"
            "    <dependency>\n"
            "      <groupId>com.google.guava</groupId>\n"
            "      <artifactId>guava</artifactId>\n"
            "      <version>32.1.3-jre</version>\n"
            "    </dependency>\n"
            "  </dependencies>\n"
            "</project>\n"
        )
        pkg = tmp_path / "package.json"
        pkg.write_text('{"dependencies": {"lodash": "^4.17.21"}}')

        manifest = ProjectManifest(
            root_path=tmp_path,
            build_tools=[
                BuildTool(name="maven", config_file="pom.xml", language="java"),
                BuildTool(
                    name="npm",
                    config_file="package.json",
                    language="javascript",
                ),
            ],
        )
        env = await resolve_dependencies(manifest)
        assert "java" in env.dependencies
        assert "javascript" in env.dependencies
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_dependencies.py -v`
Expected: FAIL (ImportError — `app.stages.dependencies` does not exist)

- [ ] **Step 3: Commit test file**

```bash
cd cast-clone-backend && git add tests/unit/test_dependencies.py && git commit -m "test(dependencies): add failing tests for Stage 2 dependency resolution"
```

---

## Task 8: Dependency Resolution — Implementation

**Files:**
- Create: `app/stages/dependencies.py`

- [ ] **Step 1: Implement resolve_dependencies()**

```python
# app/stages/dependencies.py
"""Stage 2: Dependency Resolution.

Parses build configuration files (pom.xml, package.json, pyproject.toml,
requirements.txt, .csproj) to extract declared dependencies. For Phase 1,
we only parse declaration files — we do NOT run build tools (mvn, npm, etc.).

This is ASYNC to future-proof for subprocess-based resolution in later phases.
"""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import structlog

from app.models.manifest import (
    BuildTool,
    ProjectManifest,
    ResolvedDependency,
    ResolvedEnvironment,
)

logger = structlog.get_logger(__name__)

# Maven POM namespace
_MVN_NS = {"mvn": "http://maven.apache.org/POM/4.0.0"}


# ── Public API ───────────────────────────────────────────────────


async def resolve_dependencies(
    manifest: ProjectManifest,
) -> ResolvedEnvironment:
    """Stage 2 entry point: parse build files and extract dependency declarations.

    For Phase 1, this does NOT run build tools (mvn dependency:tree, npm install).
    It only parses the declaration files directly, which is fast and requires no
    build toolchain.

    Args:
        manifest: The ProjectManifest produced by Stage 1.

    Returns:
        ResolvedEnvironment with dependencies keyed by language.
    """
    start = time.monotonic()
    log = logger.bind(project_root=str(manifest.root_path))
    log.info("dependencies.start", stage="dependencies")

    dependencies: dict[str, list[ResolvedDependency]] = {}
    errors: list[str] = []

    for tool in manifest.build_tools:
        config_path = manifest.root_path / tool.config_file
        language = tool.language

        try:
            deps = _parse_for_tool(tool, config_path)
            if deps:
                existing = dependencies.get(language, [])
                existing.extend(deps)
                dependencies[language] = existing
        except Exception as e:
            msg = f"Failed to parse {tool.config_file} ({tool.name}): {e}"
            log.warning("dependencies.parse_error", error=msg)
            errors.append(msg)

    elapsed = time.monotonic() - start
    dep_counts = {lang: len(deps) for lang, deps in dependencies.items()}
    log.info(
        "dependencies.complete",
        stage="dependencies",
        dependency_counts=dep_counts,
        error_count=len(errors),
        elapsed_seconds=round(elapsed, 3),
    )

    return ResolvedEnvironment(
        dependencies=dependencies,
        env_vars={},
        errors=errors,
    )


# ── Dispatch ─────────────────────────────────────────────────────


def _parse_for_tool(
    tool: BuildTool, config_path: Path
) -> list[ResolvedDependency]:
    """Route to the correct parser based on build tool type."""
    if tool.name == "maven":
        return parse_maven_dependencies(config_path)
    elif tool.name == "gradle":
        return _parse_gradle_dependencies(config_path)
    elif tool.name == "npm":
        return parse_npm_dependencies(config_path)
    elif tool.name in ("uv/pip", "pip"):
        return parse_python_dependencies(config_path)
    elif tool.name == "dotnet":
        return parse_dotnet_dependencies(config_path)
    return []


# ── Maven ────────────────────────────────────────────────────────


def parse_maven_dependencies(pom_path: Path) -> list[ResolvedDependency]:
    """Parse Maven pom.xml and extract <dependency> elements.

    Extracts groupId:artifactId as the name, version (may be None if managed
    by parent POM), and scope (defaults to "compile").

    Args:
        pom_path: Path to pom.xml.

    Returns:
        List of ResolvedDependency. Empty list on any parse error.
    """
    if not pom_path.is_file():
        return []

    try:
        tree = ET.parse(pom_path)  # noqa: S314
    except ET.ParseError:
        logger.warning("dependencies.maven_parse_error", path=str(pom_path))
        return []

    root = tree.getroot()
    deps: list[ResolvedDependency] = []

    # Handle both namespaced and non-namespaced POM files
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    for dep_elem in root.iter(f"{ns}dependency"):
        group_id_elem = dep_elem.find(f"{ns}groupId")
        artifact_id_elem = dep_elem.find(f"{ns}artifactId")

        if group_id_elem is None or artifact_id_elem is None:
            continue

        group_id = group_id_elem.text or ""
        artifact_id = artifact_id_elem.text or ""
        name = f"{group_id}:{artifact_id}"

        version_elem = dep_elem.find(f"{ns}version")
        version = version_elem.text if version_elem is not None else None

        scope_elem = dep_elem.find(f"{ns}scope")
        scope = scope_elem.text if scope_elem is not None else "compile"

        deps.append(
            ResolvedDependency(name=name, version=version, scope=scope)
        )

    return deps


# ── Gradle ───────────────────────────────────────────────────────


def _parse_gradle_dependencies(gradle_path: Path) -> list[ResolvedDependency]:
    """Parse Gradle build file with regex heuristics.

    Gradle build files are Groovy/Kotlin DSL, not structured data. We use
    regex to extract the most common dependency declaration patterns.
    This is a best-effort parser.

    Args:
        gradle_path: Path to build.gradle or build.gradle.kts.

    Returns:
        List of ResolvedDependency extracted via regex.
    """
    if not gradle_path.is_file():
        return []

    try:
        content = gradle_path.read_text(encoding="utf-8")
    except OSError:
        return []

    deps: list[ResolvedDependency] = []

    # Match patterns like: implementation 'group:artifact:version'
    # or: implementation("group:artifact:version")
    pattern = re.compile(
        r"""(?:implementation|api|compileOnly|runtimeOnly|testImplementation|"""
        r"""testRuntimeOnly|annotationProcessor)\s*"""
        r"""[\('"]+([^:'"]+):([^:'"]+)(?::([^'")\s]+))?['")\s]""",
        re.MULTILINE,
    )

    for match in pattern.finditer(content):
        group_id = match.group(1).strip()
        artifact_id = match.group(2).strip()
        version = match.group(3).strip() if match.group(3) else None
        name = f"{group_id}:{artifact_id}"

        # Determine scope from configuration name
        line = content[max(0, match.start() - 50) : match.start() + 5]
        scope = "compile"
        if "testImplementation" in line or "testRuntimeOnly" in line:
            scope = "test"
        elif "runtimeOnly" in line:
            scope = "runtime"
        elif "compileOnly" in line:
            scope = "compile"

        deps.append(ResolvedDependency(name=name, version=version, scope=scope))

    return deps


# ── npm ──────────────────────────────────────────────────────────


def parse_npm_dependencies(package_json_path: Path) -> list[ResolvedDependency]:
    """Parse package.json and extract dependencies + devDependencies.

    Args:
        package_json_path: Path to package.json.

    Returns:
        List of ResolvedDependency. Production deps get scope "compile",
        dev deps get scope "dev". Empty list on any parse error.
    """
    if not package_json_path.is_file():
        return []

    try:
        data = json.loads(package_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning(
            "dependencies.npm_parse_error", path=str(package_json_path)
        )
        return []

    deps: list[ResolvedDependency] = []

    for name, version in data.get("dependencies", {}).items():
        deps.append(
            ResolvedDependency(name=name, version=version, scope="compile")
        )

    for name, version in data.get("devDependencies", {}).items():
        deps.append(
            ResolvedDependency(name=name, version=version, scope="dev")
        )

    return deps


# ── Python ───────────────────────────────────────────────────────


# Regex to split a PEP 508 dependency specifier into name and version
_PEP508_PATTERN = re.compile(
    r"^([a-zA-Z0-9][-a-zA-Z0-9_.]*)"  # package name
    r"(?:\[[-a-zA-Z0-9_.,\s]*\])?"  # optional extras like [standard]
    r"(.*)$"  # version specifier remainder
)


def parse_python_dependencies(
    config_path: Path,
) -> list[ResolvedDependency]:
    """Parse Python dependency files (requirements.txt or pyproject.toml).

    For requirements.txt: parses each line as a PEP 508 dependency.
    For pyproject.toml: extracts [project].dependencies array.

    Args:
        config_path: Path to requirements.txt or pyproject.toml.

    Returns:
        List of ResolvedDependency. Empty list on any parse error.
    """
    if not config_path.is_file():
        return []

    if config_path.name == "pyproject.toml":
        return _parse_pyproject_toml(config_path)
    else:
        return _parse_requirements_txt(config_path)


def _parse_requirements_txt(req_path: Path) -> list[ResolvedDependency]:
    """Parse requirements.txt format."""
    try:
        content = req_path.read_text(encoding="utf-8")
    except OSError:
        return []

    deps: list[ResolvedDependency] = []

    for line in content.splitlines():
        line = line.strip()

        # Skip empty lines, comments, and options
        if not line or line.startswith("#") or line.startswith("-"):
            continue

        dep = _parse_pep508_line(line)
        if dep is not None:
            deps.append(dep)

    return deps


def _parse_pyproject_toml(toml_path: Path) -> list[ResolvedDependency]:
    """Parse pyproject.toml [project].dependencies array."""
    try:
        import tomllib
    except ImportError:
        # Python < 3.11 fallback (should not happen with 3.12)
        return []

    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        logger.warning(
            "dependencies.pyproject_parse_error", path=str(toml_path)
        )
        return []

    deps: list[ResolvedDependency] = []
    dep_strings = data.get("project", {}).get("dependencies", [])

    for dep_str in dep_strings:
        dep = _parse_pep508_line(dep_str.strip())
        if dep is not None:
            deps.append(dep)

    return deps


def _parse_pep508_line(line: str) -> ResolvedDependency | None:
    """Parse a single PEP 508 dependency specifier line.

    Examples:
        "flask==3.0.0" -> ResolvedDependency(name="flask", version="3.0.0")
        "requests>=2.31.0" -> ResolvedDependency(name="requests", version=">=2.31.0")
        "numpy" -> ResolvedDependency(name="numpy", version=None)
        "uvicorn[standard]>=0.24.0" -> ResolvedDependency(name="uvicorn", version=">=0.24.0")

    Args:
        line: A single dependency specifier string.

    Returns:
        ResolvedDependency or None if the line cannot be parsed.
    """
    match = _PEP508_PATTERN.match(line)
    if not match:
        return None

    name = match.group(1).strip()
    version_part = match.group(2).strip()

    # Clean up version: "==3.0.0" -> "3.0.0", ">=2.31.0" -> ">=2.31.0"
    version: str | None = None
    if version_part:
        if version_part.startswith("=="):
            version = version_part[2:].strip()
        elif version_part:
            version = version_part.strip()

    return ResolvedDependency(name=name, version=version, scope="compile")


# ── .NET ─────────────────────────────────────────────────────────


def parse_dotnet_dependencies(csproj_path: Path) -> list[ResolvedDependency]:
    """Parse .csproj XML and extract <PackageReference> elements.

    Args:
        csproj_path: Path to a .csproj file.

    Returns:
        List of ResolvedDependency. Empty list on any parse error.
    """
    if not csproj_path.is_file():
        return []

    try:
        tree = ET.parse(csproj_path)  # noqa: S314
    except ET.ParseError:
        logger.warning(
            "dependencies.dotnet_parse_error", path=str(csproj_path)
        )
        return []

    root = tree.getroot()
    deps: list[ResolvedDependency] = []

    # .csproj files may or may not have a namespace
    for pkg_ref in root.iter("PackageReference"):
        name = pkg_ref.get("Include")
        if not name:
            continue
        version = pkg_ref.get("Version")

        deps.append(
            ResolvedDependency(name=name, version=version, scope="compile")
        )

    return deps
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_dependencies.py -v`
Expected: PASS (all tests green)

- [ ] **Step 3: Commit**

```bash
cd cast-clone-backend && git add app/stages/dependencies.py && git commit -m "feat(stages): implement Stage 2 dependency resolution for Maven, npm, Python, and .NET"
```

---

## Task 9: Full Test Suite Run

- [ ] **Step 1: Run all tests together**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_discovery.py tests/unit/test_dependencies.py -v --tb=short`
Expected: ALL PASS

- [ ] **Step 2: Run with coverage**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_discovery.py tests/unit/test_dependencies.py --cov=app/stages --cov-report=term-missing -v`
Expected: Coverage > 90% for both `app/stages/discovery.py` and `app/stages/dependencies.py`

- [ ] **Step 3: Lint check**

Run: `cd cast-clone-backend && uv run ruff check app/stages/ && uv run ruff format --check app/stages/`
Expected: No errors

- [ ] **Step 4: Final commit (if any lint fixes needed)**

```bash
cd cast-clone-backend && git add -A && git commit -m "chore: lint fixes for discovery and dependencies stages"
```

---

## Summary

After completing M3, the system has:

1. **Stage 1 — `discover_project()`** in `app/stages/discovery.py`:
   - Walks filesystem recursively, skipping hidden/build/vendor dirs
   - Detects 6 languages by extension (java, python, typescript, javascript, csharp, sql)
   - Counts LOC per file (skips comments and blank lines)
   - Detects 6 build tool types (maven, gradle, npm, uv/pip, pip, dotnet)
   - Detects 9 frameworks (spring-boot, hibernate, spring-data-jpa, express, react, nestjs, angular, django, fastapi, aspnet)
   - Returns a fully populated `ProjectManifest`

2. **Stage 2 — `resolve_dependencies()`** in `app/stages/dependencies.py`:
   - Parses Maven pom.xml (groupId:artifactId, version, scope)
   - Parses Gradle build files (regex-based best-effort)
   - Parses npm package.json (dependencies + devDependencies)
   - Parses Python requirements.txt and pyproject.toml (PEP 508)
   - Parses .NET .csproj (PackageReference elements)
   - Returns a `ResolvedEnvironment` keyed by language

3. **Test fixtures** in `tests/fixtures/`:
   - `raw-java/` — Spring Boot + Hibernate project (pom.xml + 2 Java files)
   - `express-app/` — Express.js project (package.json + 1 JS file)
   - `spring-petclinic/` — Multi-file Spring Boot project (pom.xml + 5 Java files)

These fixtures are reused by later milestones (tree-sitter parsing, SCIP indexing, framework plugins).
