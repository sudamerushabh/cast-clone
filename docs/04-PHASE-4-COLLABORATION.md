# Phase 4 — Collaboration & Team Features (Revised)

**Timeline:** Months 7–9
**Goal:** Let a second person use the tool — login, shared projects, saved findings
**Last Updated:** Simplified — minimum viable multi-user, not enterprise collaboration platform

---

## Overview

Phases 1-3 work for a single user exploring their own codebase. Phase 4 adds the minimum so a **team** can use it: user accounts, shared projects, annotations to capture knowledge, saved views to share findings, and data export.

**What Phase 4 is NOT:** an enterprise collaboration platform with SAML SSO, 5-role RBAC, workspace hierarchies, and audit compliance. That's Phase 6 territory. Phase 4 is "add a login screen, let people save their work, let teammates see it."

---

## 1. Authentication

### Local Accounts with JWT

For on-premise, start with local username/password accounts and JWT tokens. FastAPI has built-in support.

**Dependencies:**
```bash
pip install python-jose[cryptography] passlib[bcrypt] python-multipart
```

**Implementation (~150 lines):**

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta

SECRET_KEY = os.environ["SECRET_KEY"]
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

def verify_password(plain, hashed) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict) -> str:
    expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    return jwt.encode({**data, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user = await get_user_by_id(payload["sub"])
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
```

**That's the entire auth system for Phase 4.** No OAuth providers, no OIDC discovery, no SAML. Just bcrypt passwords + JWT tokens.

### Two Roles: Admin and Member

| Role | Can Do |
|------|--------|
| **Admin** | Everything: manage users, create/delete projects, configure system |
| **Member** | Use projects: explore graphs, add annotations, save views, export |

```python
from enum import Enum

class Role(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"

def require_admin(user: User = Depends(get_current_user)):
    if user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
```

Two roles. One `if` statement. Done.

### First-Run Setup

On first launch (no users in DB), show a setup screen to create the initial admin account. After that, admins can create member accounts.

---

## 2. User Management

### Database Schema (PostgreSQL)

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'member',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT now(),
    last_login TIMESTAMP
);
```

### API Endpoints

```
POST /api/v1/auth/login         → Returns JWT token
POST /api/v1/auth/logout        → Client-side (discard token)
GET  /api/v1/users/me           → Current user profile
GET  /api/v1/users              → List users (admin only)
POST /api/v1/users              → Create user (admin only)
PUT  /api/v1/users/{id}         → Update user (admin only)
DELETE /api/v1/users/{id}       → Deactivate user (admin only)
```

### Frontend

- Login page (username + password form)
- User menu in the top-right corner (profile, logout)
- Admin page: user list with create/edit/deactivate buttons
- No signup page — admins create accounts. This is an on-prem tool, not a SaaS.

---

## 3. Annotations & Tags

Let team members capture knowledge about the codebase directly on graph nodes.

### Annotations

Free-text notes attached to any node. "This service is being deprecated in Q3" or "Performance bottleneck — see JIRA-1234."

```sql
CREATE TABLE annotations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id),
    node_fqn VARCHAR(500) NOT NULL,
    content TEXT NOT NULL,
    author_id UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
CREATE INDEX idx_annotations_node ON annotations(project_id, node_fqn);
```

### Tags

Predefined labels for quick categorization:

- `deprecated` — scheduled for removal
- `tech-debt` — needs refactoring
- `critical-path` — high-impact, handle with care
- `security-sensitive` — extra review needed
- `needs-review` — flagged for team discussion

```sql
CREATE TABLE tags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id),
    node_fqn VARCHAR(500) NOT NULL,
    tag_name VARCHAR(100) NOT NULL,
    author_id UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMP DEFAULT now(),
    UNIQUE(project_id, node_fqn, tag_name)
);
CREATE INDEX idx_tags_node ON tags(project_id, node_fqn);
CREATE INDEX idx_tags_name ON tags(project_id, tag_name);
```

### API Endpoints

```
POST   /api/v1/projects/{id}/annotations    → Create annotation on a node
GET    /api/v1/projects/{id}/annotations?node_fqn=...  → Get annotations for a node
PUT    /api/v1/annotations/{id}             → Edit annotation (author only)
DELETE /api/v1/annotations/{id}             → Delete annotation (author or admin)

POST   /api/v1/projects/{id}/tags           → Add tag to node(s)
GET    /api/v1/projects/{id}/tags?node_fqn=...  → Get tags for a node
GET    /api/v1/projects/{id}/tags?tag_name=deprecated  → Get all nodes with a tag
DELETE /api/v1/tags/{id}                    → Remove tag
```

### Frontend

- **Node properties panel:** Show annotations and tags for the selected node
- **Add annotation:** Text input at the bottom of the properties panel
- **Add tag:** Dropdown of predefined tags in the properties panel
- **Filter by tag:** In the sidebar, add a "Tags" filter section — click a tag to highlight all nodes with that tag
- **Visual indicators:** Nodes with annotations show a small icon overlay. Nodes tagged `deprecated` get a strikethrough style.

---

## 4. Saved Views

Let users save the current graph state and share it with teammates.

### What Gets Saved

A saved view captures:
- Which view type is active (architecture, dependency, transaction)
- Which nodes are currently visible (the drill-down state)
- The current layout configuration
- The zoom level and pan position
- Any active filters
- Which transaction is selected (if in transaction view)
- Any active impact analysis or path highlighting

### Database Schema

```sql
CREATE TABLE saved_views (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    author_id UUID NOT NULL REFERENCES users(id),
    state JSONB NOT NULL,    -- serialized Cytoscape + app state
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
CREATE INDEX idx_views_project ON saved_views(project_id);
```

The `state` column stores the full UI state as JSON:

```json
{
  "viewType": "transaction",
  "selectedTransaction": "POST /api/users → UserController.create",
  "visibleNodeFqns": ["com.app.UserController", "com.app.UserService", ...],
  "layout": {"name": "dagre", "rankDir": "LR"},
  "zoom": 1.5,
  "pan": {"x": 200, "y": 100},
  "filters": {"nodeTypes": ["Class", "Function"], "languages": ["java"]},
  "highlights": {
    "impact": {"startNode": "com.app.UserService.createUser", "depth": 3}
  }
}
```

### API Endpoints

```
POST /api/v1/projects/{id}/views          → Save current view
GET  /api/v1/projects/{id}/views          → List all saved views for project
GET  /api/v1/views/{id}                   → Load a saved view
PUT  /api/v1/views/{id}                   → Update view (author only)
DELETE /api/v1/views/{id}                 → Delete view (author or admin)
```

### Frontend

- **Save button** in the toolbar → opens a modal: name + optional description
- **Views panel** in the sidebar → list of saved views for this project, with author name and date
- **Click a saved view** → restores the graph to that exact state
- **Share URL:** Each saved view has a URL: `/projects/{id}/views/{viewId}`. Copy-paste to Slack or docs.

All saved views are visible to all project members. No per-view permissions. Keep it simple.

---

## 5. Data Export

Phase 2 already has PNG/SVG/JSON export from Cytoscape. Phase 4 adds structured data export:

### CSV Export

Export node and edge lists as CSV files for analysis in Excel/Google Sheets:

```
GET /api/v1/export/{project}/nodes.csv
    ?type=class,function&fields=fqn,name,loc,complexity,communityId
    
GET /api/v1/export/{project}/edges.csv
    ?type=CALLS,DEPENDS_ON&fields=source,target,type,weight
```

Implementation: query Neo4j, stream results as CSV using Python's `csv` module + FastAPI `StreamingResponse`. ~30 lines of code.

### JSON Export

Export full graph data as JSON:

```
GET /api/v1/export/{project}/graph.json
    ?level=module    → Module-level graph with aggregated edges
    ?level=class     → Full class-level graph
```

### Impact Analysis Export

Export an impact analysis result as CSV:

```
GET /api/v1/export/{project}/impact.csv
    ?node={fqn}&direction=both&maxDepth=5
```

Returns: `fqn, name, type, depth, file, line` — ready for a spreadsheet review.

**No PDF or DOCX report generation in Phase 4.** That's Phase 6 enterprise reporting. CSV and JSON cover all practical needs.

---

## 6. Activity Log

Simple action logging — not a compliance audit trail, just "what happened."

```sql
CREATE TABLE activity_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50),        -- project, annotation, view, etc.
    resource_id UUID,
    details JSONB,                    -- action-specific metadata
    created_at TIMESTAMP DEFAULT now()
);
CREATE INDEX idx_activity_time ON activity_log(created_at DESC);
CREATE INDEX idx_activity_user ON activity_log(user_id);
```

**Actions logged:**
- `user.login`, `user.created`
- `project.created`, `project.deleted`
- `analysis.started`, `analysis.completed`, `analysis.failed`
- `annotation.created`, `annotation.deleted`
- `view.saved`, `view.deleted`

**API:**
```
GET /api/v1/activity?limit=50&user_id=...&action=...
    → Recent activity feed (admin only)
```

**Frontend:** An activity feed page (admin only) showing recent actions as a simple chronological list. No charts, no analytics.

---

## 7. Project Management Enhancements

Phase 1 has basic project CRUD. Phase 4 adds:

### Project Settings

- **Name and description** (editable)
- **Re-analyze button** (trigger a fresh analysis)
- **Analysis config:** toggle framework plugins on/off, set analysis timeout
- **Delete project** (admin only, with confirmation)

### Project List Dashboard

- Cards showing: project name, last analyzed date, languages, node/edge counts, warning count
- Sort by: name, last analyzed, size
- Quick action buttons: open, re-analyze, delete

---

## 8. API Endpoints Summary (Phase 4)

```
# Auth
POST /api/v1/auth/login
GET  /api/v1/users/me
GET  /api/v1/users                      (admin)
POST /api/v1/users                      (admin)
PUT  /api/v1/users/{id}                 (admin)

# Annotations
POST   /api/v1/projects/{id}/annotations
GET    /api/v1/projects/{id}/annotations?node_fqn=...
PUT    /api/v1/annotations/{id}
DELETE /api/v1/annotations/{id}

# Tags
POST   /api/v1/projects/{id}/tags
GET    /api/v1/projects/{id}/tags?node_fqn=...
GET    /api/v1/projects/{id}/tags?tag_name=...
DELETE /api/v1/tags/{id}

# Saved Views
POST   /api/v1/projects/{id}/views
GET    /api/v1/projects/{id}/views
GET    /api/v1/views/{id}
PUT    /api/v1/views/{id}
DELETE /api/v1/views/{id}

# Export
GET /api/v1/export/{project}/nodes.csv
GET /api/v1/export/{project}/edges.csv
GET /api/v1/export/{project}/graph.json
GET /api/v1/export/{project}/impact.csv?node=...

# Activity
GET /api/v1/activity                    (admin)

# Projects (enhanced)
PUT /api/v1/projects/{id}/settings
```

---

## 9. What's Explicitly Deferred

| Feature | Deferred To | Why |
|---------|------------|-----|
| OAuth 2.0 / OIDC (Okta, Azure AD, Google) | Phase 6 | Enterprise feature, no customer demand yet |
| SAML 2.0 | Phase 6 | Complex, enterprise-only |
| 5-role RBAC (Admin, Owner, Editor, Viewer, API) | Phase 6 | Admin + Member is enough for teams |
| Workspaces / organizational hierarchy | Phase 6 | Projects are the organization unit |
| API key management | Phase 5 | MCP server needs it first |
| Per-view sharing permissions | Phase 6 | All views visible to project members |
| Annotation version history | Phase 6 | Current annotation is enough |
| Sticky notes on canvas | Phase 6 | Annotations on nodes cover this |
| PDF/DOCX report generation | Phase 6 | CSV/JSON export is sufficient |
| Compliance-grade audit trail | Phase 6 | Simple activity log is enough |

---

## 10. Deliverables Checklist

### Authentication & Users
- [ ] JWT-based auth (login, token validation, password hashing)
- [ ] First-run admin setup screen
- [ ] User management API (CRUD, admin only)
- [ ] Two-role system (admin + member)
- [ ] Login page
- [ ] User menu (profile, logout)
- [ ] Admin user management page

### Annotations & Tags
- [ ] Annotations CRUD API
- [ ] Tags CRUD API
- [ ] Annotations display in node properties panel
- [ ] Tags display in node properties panel
- [ ] Add annotation / add tag UI in properties panel
- [ ] Filter by tag in sidebar
- [ ] Visual indicator on annotated/tagged nodes

### Saved Views
- [ ] Save view API (serialize Cytoscape + app state to JSONB)
- [ ] Load view API (restore state)
- [ ] Views list in sidebar
- [ ] Save button in toolbar
- [ ] Shareable view URLs

### Export
- [ ] CSV export (nodes, edges, impact results)
- [ ] JSON export (graph data)
- [ ] Export buttons in toolbar

### Activity & Projects
- [ ] Activity log table + API
- [ ] Activity feed page (admin)
- [ ] Project settings page
- [ ] Project dashboard (cards with stats)

---

## 11. Success Criteria

Phase 4 is complete when:

1. Multiple users can log in and access the same project
2. Users can add annotations and tags to nodes, and teammates see them
3. Users can save a view and a teammate can open it via URL, seeing the exact same graph state
4. CSV export downloads correctly formatted data that opens in Excel
5. Admin can create/deactivate user accounts
6. Activity log shows who analyzed what and when