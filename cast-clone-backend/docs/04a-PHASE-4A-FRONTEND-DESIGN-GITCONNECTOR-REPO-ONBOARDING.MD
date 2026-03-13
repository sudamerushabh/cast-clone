# M7 Architecture & API Design — Product Shell, Git Connectors, Repo Onboarding

**Scope:** Three milestones that transform CodeLens from a dev tool into a product
**Dependencies:** Phase 2 M2 (frontend foundation), Phase 1 M1-M2 (backend foundation)
**Auth dependency:** None — designed for single-user mode now, ready for Phase 4 auth later
**Last Updated:** 2026-03-13

---

## Overview

CodeLens currently has a project-scoped sidebar (Dashboard, Architecture, Dependencies, etc.) that only appears inside `/projects/[id]`. There is no global navigation, no way to manage source integrations, and project creation requires pasting a local filesystem path.

M7 adds three things:

1. **M7a: Global Navigation Shell** — App-level sidebar with icon rail, route restructuring, top bar redesign
2. **M7b: Git Connectors** — Backend model + API + UI for connecting to GitHub, GitLab, Gitea, Bitbucket
3. **M7c: Repo Onboarding** — Multi-step "Add Source" flow with multi-branch support, clone, and analysis

After M7, a new user's journey is: open CodeLens → add a GitHub connector → browse repos → pick one → select branches → clone + analyze. No terminal, no filesystem paths, no Docker volume mounts.

---

## Key Decisions (Resolved)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Clone depth | **Full clone** | Enables future git-blame, history analysis, and proper git pull for re-sync |
| Repo list caching | **No cache** — always fetch live | Simplicity; avoids stale data for newly created repos |
| Multi-branch model | **Option C** — branches as separate projects, versioning via PostgreSQL snapshots | Clean Neo4j isolation per branch, no graph bloat from historical versions |
| Repository in navigation | **First-class entity** — nav shows Repositories, drill in to see branches | Matches developer mental model, cleaner than flat project list |
| Connector auth (v1) | **PAT only** | Works with all providers including self-hosted; OAuth deferred to v2 |
| Connector ownership | **Per-user** when Phase 4 auth lands | Your PAT, your repos; simpler permission model |
| Azure DevOps | **Deferred** | Different API pattern; GitHub/GitLab/Gitea/Bitbucket cover the primary market |

---

## 1. Entity Model

M7 introduces two new entities and restructures the relationship between existing ones.

### 1.1 Entity Hierarchy

```
GitConnector (per-user auth to a Git provider)
  │
  └── Repository (a remote repo, e.g. "acme/payment-service")
        │
        ├── Project: main branch      → Neo4j graph (app_name = "{repo_id}:main")
        ├── Project: develop branch   → Neo4j graph (app_name = "{repo_id}:develop")
        └── Project: feature/auth     → Neo4j graph (app_name = "{repo_id}:feature/auth")
              │
              └── AnalysisRun (with snapshot JSON for versioning)
```

Key relationships:
- A Connector authenticates with a Git provider and can browse its repos
- A Repository is a remote repo (linked to one connector) cloned to local storage
- A Project is a single branch of a repository, with its own Neo4j graph
- An AnalysisRun records one analysis execution, with a lightweight snapshot for evolution tracking

Backward compatibility: Projects created with local paths (pre-M7) have repository_id = null and continue working exactly as before.

### 1.2 Data Models (SQLAlchemy)

#### GitConnector

```python
class GitConnector(Base):
    __tablename__ = "git_connectors"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # github | gitlab | gitea | bitbucket
    base_url: Mapped[str] = mapped_column(
        String(1024), nullable=False
    )  # https://github.com, https://gitlab.company.com, etc.
    auth_method: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pat"
    )  # pat | oauth (v2)
    encrypted_token: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # Fernet-encrypted PAT
    status: Mapped[str] = mapped_column(
        String(50), default="connected"
    )  # connected | expired | revoked | error
    remote_username: Mapped[str | None] = mapped_column(
        String(255)
    )  # populated after first validation
    created_by: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )  # nullable now, FK to users.id in Phase 4
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    repositories: Mapped[list[Repository]] = relationship(
        back_populates="connector", cascade="all, delete-orphan"
    )
```

#### Repository (new entity)

```python
class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    connector_id: Mapped[str] = mapped_column(
        ForeignKey("git_connectors.id", ondelete="CASCADE"), nullable=False
    )
    repo_full_name: Mapped[str] = mapped_column(
        String(512), nullable=False
    )  # "owner/repo-name"
    repo_clone_url: Mapped[str] = mapped_column(
        String(1024), nullable=False
    )  # HTTPS clone URL (token NOT embedded)
    default_branch: Mapped[str] = mapped_column(
        String(255), nullable=False, default="main"
    )
    description: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(100))
    is_private: Mapped[bool] = mapped_column(default=False)
    local_path: Mapped[str | None] = mapped_column(
        String(1024)
    )  # /data/repos/{repo_id}/ — set after first clone
    clone_status: Mapped[str] = mapped_column(
        String(50), default="pending"
    )  # pending | cloning | cloned | clone_failed
    clone_error: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_by: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )  # nullable now, FK to users.id in Phase 4
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    connector: Mapped[GitConnector] = relationship(back_populates="repositories")
    projects: Mapped[list[Project]] = relationship(
        back_populates="repository", cascade="all, delete-orphan"
    )
```

#### Project (modified — adds repository link + branch)

```python
class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), default="created"
    )  # created | analyzing | analyzed | failed

    # New fields for M7
    repository_id: Mapped[str | None] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), nullable=True
    )  # null for local-path projects
    branch: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # "main", "develop", "feature/auth" — null for local-path

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    repository: Mapped[Repository | None] = relationship(back_populates="projects")
    analysis_runs: Mapped[list[AnalysisRun]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    @property
    def neo4j_app_name(self) -> str:
        """The app_name used in Neo4j to namespace this project's graph."""
        if self.repository_id and self.branch:
            return f"{self.repository_id}:{self.branch}"
        return self.id  # legacy local-path projects
```

#### AnalysisRun (modified — adds snapshot for versioning)

```python
class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    # ... existing fields unchanged ...

    # New fields for evolution tracking
    snapshot: Mapped[dict | None] = mapped_column(JSON)
    # Snapshot schema:
    # {
    #     "commit_sha": "abc123def",
    #     "branch": "main",
    #     "summary": {
    #         "node_count": 1234,
    #         "edge_count": 5678,
    #         "module_count": 15,
    #         "class_count": 340,
    #         "function_count": 1800,
    #         "api_endpoint_count": 45,
    #         "table_count": 12,
    #         "transaction_count": 28,
    #         "total_loc": 42000,
    #         "avg_complexity": 4.2,
    #         "community_count": 8
    #     },
    #     "languages": {"java": 35000, "sql": 2000, "typescript": 5000},
    #     "frameworks": ["spring-boot", "hibernate", "react"],
    #     "modules": [
    #         {
    #             "fqn": "com.acme.payment",
    #             "name": "payment",
    #             "class_count": 24,
    #             "function_count": 120,
    #             "loc": 3400,
    #             "avg_complexity": 5.1
    #         }
    #     ]
    # }
    commit_sha: Mapped[str | None] = mapped_column(String(40))
```

### 1.3 Neo4j Namespace Strategy

Each branch-project gets its own isolated namespace in Neo4j:

| Project type | Neo4j app_name | Example |
|---|---|---|
| Repo branch | {repo_id}:{branch} | a1b2c3:main |
| Repo branch | {repo_id}:{branch} | a1b2c3:develop |
| Legacy local path | {project_id} | d4e5f6 (unchanged) |

Re-analysis behavior (unchanged): Delete all nodes where app_name = X, then write fresh. Only the latest graph per branch exists in Neo4j at any time.

Cross-branch comparison: Done via PostgreSQL snapshot JSON, not Neo4j. Compare the snapshot.summary and snapshot.modules arrays between two AnalysisRuns on different branches.

---

## 2. Global Navigation Shell (M7a)

### 2.1 Navigation Architecture

Two-panel sidebar: A 48px icon rail (always visible) + a 240px contextual panel that changes based on where you are.

```
┌──────────────────────────────────────────────────────┐
│  Top Bar (h-11): Logo + breadcrumbs + search + user  │
├────┬──────────┬──────────────────────────────────────┤
│    │          │                                      │
│ 48 │  240px   │         Main Content Area            │
│ px │ Context  │                                      │
│    │  Panel   │   (graph, dashboard, settings, etc.) │
│ I  │          │                                      │
│ c  │ Changes  │                                      │
│ o  │ based on │                                      │
│ n  │ active   │                                      │
│    │ section  │                                      │
│ R  │          │                                      │
│ a  ├──────────┤                                      │
│ i  │          │                                      │
│ l  │          │                                      │
│    │          │                                      │
├────┴──────────┴──────────────────────────────────────┤
│  (optional right panel for node properties)          │
└──────────────────────────────────────────────────────┘
```

### 2.2 Icon Rail Items

| Position | Icon | Label | Route | Context Panel |
|----------|------|-------|-------|---------------|
| Top | LayoutDashboard | Home | / | Recent activity, quick actions |
| Top | FolderGit2 | Repositories | /repositories | Repository list (compact) |
| Top | GitBranch | Connectors | /connectors | Connector list |
| Top | Settings | Settings | /settings | Settings nav (System, AI) |
| Bottom | User | User | — | Dropdown: theme toggle, profile placeholder |

When inside a project (/repositories/[repoId]/[branch]/*), the context panel switches to project-level navigation:

| Icon | Label | Route |
|------|-------|-------|
| LayoutDashboard | Overview | /repositories/[repoId]/[branch] |
| GitGraph | Architecture | /repositories/[repoId]/[branch]/graph |
| FolderOpen | Dependencies | /repositories/[repoId]/[branch]/dependencies |
| Route | Transactions | /repositories/[repoId]/[branch]/transactions |
| Search | Search | /repositories/[repoId]/[branch]/search |
| Zap | Impact | /repositories/[repoId]/[branch]/impact |
| BookmarkPlus | Saved Views | /repositories/[repoId]/[branch]/views |
| MessageSquare | AI Assistant | /repositories/[repoId]/[branch]/chat |
| Settings | Project Settings | /repositories/[repoId]/[branch]/settings |

A back arrow at the top of the project context panel returns to the repository view.

### 2.3 Route Structure (Next.js App Router)

```
/                                               → home dashboard (recent activity)
/repositories                                   → repository list (cards with branches)
/repositories/[repoId]                          → repository detail (branches, evolution)
/repositories/[repoId]/evolution                → evolution timeline (snapshot charts)
/repositories/[repoId]/[branch]                 → project overview for this branch
/repositories/[repoId]/[branch]/graph           → graph explorer
/repositories/[repoId]/[branch]/dependencies    → dependency view
/repositories/[repoId]/[branch]/transactions    → transaction view
/repositories/[repoId]/[branch]/search          → search
/repositories/[repoId]/[branch]/impact          → impact analysis (Phase 3 placeholder)
/repositories/[repoId]/[branch]/views           → saved views (Phase 4 placeholder)
/repositories/[repoId]/[branch]/chat            → AI assistant (Phase 5 placeholder)
/repositories/[repoId]/[branch]/settings        → project settings
/connectors                                     → connector management
/connectors/new                                 → add new connector
/settings                                       → redirect to /settings/system
/settings/system                                → system configuration
/settings/ai                                    → AI config (Phase 5 placeholder)
/settings/team                                  → team management (Phase 4 placeholder)
/projects                                       → LEGACY redirect to /repositories
/projects/[id]                                  → LEGACY — local-path projects still work
```

URL encoding note: Branch names with / (e.g., feature/auth) are URL-encoded in the path segment. Next.js catch-all routes handle this: [...branch] or explicit encoding/decoding.

### 2.4 Frontend File Structure Changes

```
cast-clone-frontend/
├── app/
│   ├── layout.tsx                              # MODIFY — wrap with GlobalShell
│   ├── page.tsx                                # MODIFY — home dashboard
│   ├── repositories/
│   │   ├── page.tsx                            # CREATE — repository list
│   │   └── [repoId]/
│   │       ├── page.tsx                        # CREATE — repo detail (branches)
│   │       ├── evolution/
│   │       │   └── page.tsx                    # CREATE — evolution timeline
│   │       └── [...branch]/
│   │           ├── layout.tsx                  # CREATE — project layout
│   │           ├── page.tsx                    # CREATE — project overview
│   │           ├── graph/
│   │           │   └── page.tsx               # MOVE from /projects/[id]/graph
│   │           └── settings/
│   │               └── page.tsx               # CREATE — project settings
│   ├── connectors/
│   │   ├── page.tsx                            # CREATE — connector list
│   │   └── new/
│   │       └── page.tsx                        # CREATE — add connector
│   ├── settings/
│   │   ├── layout.tsx                          # CREATE — settings layout
│   │   ├── page.tsx                            # CREATE — redirect
│   │   ├── system/page.tsx                     # CREATE
│   │   ├── ai/page.tsx                         # CREATE — placeholder
│   │   └── team/page.tsx                       # CREATE — placeholder
│   └── projects/
│       └── [id]/
│           └── page.tsx                        # KEEP — legacy local-path support
├── components/
│   ├── layout/
│   │   ├── GlobalShell.tsx                     # CREATE — orchestrates icon rail + panel
│   │   ├── IconRail.tsx                        # CREATE — 48px permanent sidebar
│   │   ├── ContextPanel.tsx                    # CREATE — 240px collapsible panel
│   │   ├── TopBar.tsx                          # CREATE — breadcrumbs + search + user
│   │   ├── AppLayout.tsx                       # DEPRECATE
│   │   └── Sidebar.tsx                         # DEPRECATE
│   ├── repositories/
│   │   ├── RepoCard.tsx                        # CREATE — repo card with branch badges
│   │   ├── BranchSelector.tsx                  # CREATE — branch dropdown
│   │   └── EvolutionChart.tsx                  # CREATE — snapshot timeline charts
```

### 2.5 Component Design: GlobalShell

The GlobalShell wraps the entire app in app/layout.tsx. It manages:
- Icon rail state: which global section is active (derived from pathname)
- Context panel state: open/collapsed, contents determined by route
- Project context: when pathname matches /repositories/[repoId]/[branch], panel switches to project nav

### 2.6 Top Bar

```
┌─────────────────────────────────────────────────────────────┐
│ [Logo] CodeLens  /  Repositories  /  payment-service  /     │
│                     main  /  Architecture   │ [⌘K] [🌙] [👤]│
└─────────────────────────────────────────────────────────────┘
```

- Logo: always links to /
- Breadcrumbs: dynamic based on route depth
- Branch badge: when inside a project, shows current branch with dropdown to switch
- Search trigger: opens Cmd+K palette (global scope)
- Theme toggle: light/dark mode
- User avatar: placeholder; wired to auth in Phase 4

### 2.7 Interaction: Navigating Between Contexts

Home → Repository: click repo card on /repositories. Context panel shows repo-level info.

Repository → Branch/Project: click branch on /repositories/[repoId]. Panel transitions to project nav.

Branch switching: dropdown in top bar. Switching branches navigates to same page on new branch (e.g., main/graph → develop/graph).

Leaving a project: click any icon rail item. Panel returns to global content.

Collapsing the panel: toggle collapses to 0px. Icon rail remains.

---

## 3. Git Connectors (M7b)

### 3.1 Token Encryption

Fernet encryption with key derived from SECRET_KEY:

```python
# app/services/crypto.py
from cryptography.fernet import Fernet
import base64, hashlib

def _derive_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)

def encrypt_token(plaintext: str, secret_key: str) -> str:
    f = Fernet(_derive_key(secret_key))
    return f.encrypt(plaintext.encode()).decode()

def decrypt_token(ciphertext: str, secret_key: str) -> str:
    f = Fernet(_derive_key(secret_key))
    return f.decrypt(ciphertext.encode()).decode()
```

New dependency: cryptography (add via uv add cryptography).

### 3.2 Provider Adapter Pattern

```python
# app/services/git_providers/base.py
class GitProvider(ABC):
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token

    @abstractmethod
    async def validate(self) -> GitUser: ...

    @abstractmethod
    async def list_repos(self, page, per_page, search) -> tuple[list[GitRepo], bool]: ...

    @abstractmethod
    async def get_repo(self, full_name: str) -> GitRepo: ...

    @abstractmethod
    async def list_branches(self, full_name: str) -> list[str]: ...
```

### 3.3 Provider Implementations

| Provider | Default base_url | Auth header | Branches endpoint |
|----------|-----------------|-------------|-------------------|
| GitHub | https://github.com | Authorization: Bearer {token} | GET /repos/{full_name}/branches |
| GitLab | https://gitlab.com | PRIVATE-TOKEN: {token} | GET /api/v4/projects/{id}/repository/branches |
| Gitea | (must provide) | Authorization: token {token} | GET /api/v1/repos/{full_name}/branches |
| Bitbucket | https://bitbucket.org | Authorization: Bearer {token} | GET /2.0/repositories/{full_name}/refs/branches |

API URL derivation from base_url:
- GitHub cloud: https://github.com → https://api.github.com
- GitHub Enterprise: https://github.company.com → https://github.company.com/api/v3
- GitLab: {base_url}/api/v4
- Gitea: {base_url}/api/v1
- Bitbucket cloud: https://bitbucket.org → https://api.bitbucket.org/2.0

### 3.4 API Endpoints

```
POST   /api/v1/connectors                          → Create (validates token first)
GET    /api/v1/connectors                           → List all connectors
GET    /api/v1/connectors/{id}                      → Get connector details
PUT    /api/v1/connectors/{id}                      → Update (name, token)
DELETE /api/v1/connectors/{id}                      → Delete + cascade repos
POST   /api/v1/connectors/{id}/test                 → Re-validate token
GET    /api/v1/connectors/{id}/repos                → List repos (live, no cache)
GET    /api/v1/connectors/{id}/repos/{owner}/{repo} → Get single repo
GET    /api/v1/connectors/{id}/repos/{owner}/{repo}/branches → List branches
```

### 3.5 Pydantic Schemas

```python
class ConnectorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    provider: Literal["github", "gitlab", "gitea", "bitbucket"]
    base_url: str = Field(max_length=1024)
    token: str = Field(min_length=1)

class ConnectorResponse(BaseModel):
    id: str
    name: str
    provider: str
    base_url: str
    status: str
    remote_username: str | None
    repos_count: int
    created_at: datetime
    updated_at: datetime
    # token NEVER returned

class BranchListResponse(BaseModel):
    branches: list[str]
    default_branch: str
```

### 3.6 Frontend: Connectors Page

Route: /connectors — card grid of connectors. Each card: provider icon, name, status badge, repo count.

Add connector (/connectors/new): form with provider selector → name → base URL → token → "Test & Save".

### 3.7 Backend File Structure

```
cast-clone-backend/app/
├── api/connectors.py
├── models/db.py                    # add GitConnector, Repository
├── schemas/connectors.py
├── services/
│   ├── crypto.py
│   └── git_providers/
│       ├── __init__.py
│       ├── base.py
│       ├── github.py
│       ├── gitlab.py
│       ├── gitea.py
│       └── bitbucket.py
```

---

## 4. Repo Onboarding (M7c)

### 4.1 Clone Strategy

Full clone (not shallow) to /data/repos/{repo_id}/:

- git clone {authenticated_url} {target_dir}
- Full clone so git checkout {branch} and git pull work
- After clone: strip token from remote URL
- One clone per repository — all branches share the same local directory

### 4.2 Analyzing a Branch

1. git -C {repo_path} checkout {branch}
2. git -C {repo_path} pull (if re-analyzing)
3. Run pipeline with source_path = repo.local_path
4. Writer uses app_name = project.neo4j_app_name (includes branch)
5. Build snapshot JSON → store in AnalysisRun

Concurrency: serialize analysis per repository (checkout would conflict). Add git worktree support later if parallel analysis becomes a bottleneck.

### 4.3 Repository API Endpoints

```
POST   /api/v1/repositories                      → Create from connector + repo
GET    /api/v1/repositories                       → List all repositories
GET    /api/v1/repositories/{id}                  → Get repo with branches/projects
DELETE /api/v1/repositories/{id}                  → Delete repo + all branch projects
GET    /api/v1/repositories/{id}/clone-status     → Poll clone progress
POST   /api/v1/repositories/{id}/sync             → Git pull latest
POST   /api/v1/repositories/{id}/branches         → Add a new branch to analyze
GET    /api/v1/repositories/{id}/projects         → List projects (one per branch)
GET    /api/v1/repositories/{id}/evolution         → Snapshot timeline data
GET    /api/v1/repositories/{id}/compare           → Compare two branches
         ?branch_a=main&branch_b=develop
```

### 4.4 Pydantic Schemas

```python
class RepositoryCreate(BaseModel):
    connector_id: str
    repo_full_name: str
    branches: list[str]          # branches to analyze
    auto_analyze: bool = False

class RepositoryResponse(BaseModel):
    id: str
    connector_id: str
    repo_full_name: str
    default_branch: str
    description: str | None
    clone_status: str
    last_synced_at: datetime | None
    projects: list[ProjectBranchResponse]

class ProjectBranchResponse(BaseModel):
    id: str
    branch: str
    status: str
    last_analyzed_at: datetime | None
    node_count: int | None
    edge_count: int | None

class EvolutionTimelineResponse(BaseModel):
    repo_id: str
    branch: str
    snapshots: list[SnapshotPoint]

class SnapshotPoint(BaseModel):
    run_id: str
    analyzed_at: datetime
    commit_sha: str | None
    summary: dict

class BranchCompareResponse(BaseModel):
    branch_a: str
    branch_b: str
    diff: dict
```

### 4.5 Frontend: "Add Source" Flow

Multi-step modal:
1. Choose source type: Git Repository (primary) or Local Path (legacy)
2. Select connector (dropdown, or prompt to create one)
3. Browse repositories (search + paginated list)
4. Select branches (checkboxes, default branch pre-selected)
5. Configure (name, auto-analyze toggle)
6. Progress (clone polling, then success/failure)

### 4.6 Re-sync

Repo detail page shows "Sync" button:
1. POST /api/v1/repositories/{id}/sync
2. Backend: git fetch --all && git pull
3. Prompt to re-analyze branches

### 4.7 Frontend File Structure

```
cast-clone-frontend/components/repositories/
├── AddSourceModal.tsx
├── ConnectorSelector.tsx
├── RepoBrowser.tsx
├── BranchPicker.tsx
├── RepoConfigForm.tsx
├── CloneProgress.tsx
├── RepoCard.tsx
├── BranchSelector.tsx
└── EvolutionChart.tsx
```

---

## 5. Evolution Tracking

### 5.1 Snapshot Building

After every successful analysis, build a snapshot from AnalysisContext:

```python
def build_snapshot(context: AnalysisContext, commit_sha: str | None) -> dict:
    graph = context.graph
    modules = []
    for node in graph.nodes.values():
        if node.kind == NodeKind.MODULE:
            # aggregate class_count, function_count, loc, avg_complexity
            modules.append({...})
    return {
        "commit_sha": commit_sha,
        "summary": {
            "node_count": graph.node_count,
            "edge_count": graph.edge_count,
            # ... other aggregates
        },
        "languages": _count_by_language(graph),
        "frameworks": [...],
        "modules": modules,
    }
```

### 5.2 Evolution Timeline Page

Route: /repositories/[repoId]/evolution

Time-series charts from snapshot data:
- Total nodes, edges, LOC over time
- Module-level breakdown (stacked area)
- Complexity trends per module
- Branch filter: one branch or overlay multiple

### 5.3 Cross-Branch Comparison

On repo detail page: side-by-side snapshot comparison
- Delta cards: "+250 nodes", "+12 API endpoints"
- Modules only in branch A / only in branch B
- Module-level metric differences

---

## 6. Security

- PATs encrypted at rest (Fernet AES-128-CBC + HMAC-SHA256)
- Encryption key from SECRET_KEY via SHA-256
- Tokens NEVER in API responses or logs
- Clone URLs: token injected in-memory, stripped after clone
- Pre-auth: endpoints open. Phase 4: JWT required, connectors per-user

---

## 7. Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| SECRET_KEY | change-me-in-production | Token encryption + future JWT |
| REPO_STORAGE_PATH | /data/repos | Base directory for cloned repositories |
| GIT_CLONE_TIMEOUT | 600 | Clone timeout in seconds |

Docker Compose:
```yaml
volumes:
  repo-storage:
services:
  backend:
    volumes:
      - repo-storage:/data/repos
```

---

## 8. Migration Path

### Existing local-path projects
- repository_id = null, branch = null → work exactly as before
- Shown in "Local Projects" section on repositories page
- All existing /api/v1/projects/* endpoints continue working

### Phase 4 auth integration
- created_by fields → become FK to users.id, non-nullable with backfill
- Connector API → filtered by current user (members) or all (admin)
- User menu → wired to real login/logout

---

## 9. Milestone Dependency Chain

```
M7a (Nav Shell) ← pure frontend, no backend changes
    │
    ▼
M7b (Connectors) ← needs M7a for /connectors route
    │               backend: GitConnector model, crypto, providers, API
    ▼
M7c (Onboarding) ← needs M7b for connector + repo browsing
                    backend: Repository model, clone service, Project changes,
                             snapshot builder, evolution API
```

Estimated timeline: ~4 weeks total.