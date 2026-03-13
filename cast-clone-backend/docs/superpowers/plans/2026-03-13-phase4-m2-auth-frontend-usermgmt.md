# Phase 4 M2: Auth Frontend + User Management — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add login UI, auth state management, protected routes, user menu, and admin user management — completing the end-to-end auth flow.

**Architecture:** React AuthContext provider wraps the app, storing JWT in localStorage. API client adds Authorization header automatically. Login page redirects to setup if no users exist. TopBar gets a UserMenu dropdown. Admin-only /settings/team page provides user CRUD. Backend gets user management endpoints (admin only).

**Tech Stack:** Next.js (App Router), React Context, TypeScript, Tailwind CSS, FastAPI, SQLAlchemy async

**Dependencies:** Phase 4 M1 (auth foundation — User model, JWT, login endpoint, dependencies)

**Spec Reference:** `cast-clone-backend/docs/04-PHASE-4-COLLABORATION.md` §1 (Authentication frontend), §2 (User Management)

---

## File Structure

```
cast-clone-backend/
├── app/
│   ├── api/
│   │   └── users.py                    # CREATE — user CRUD endpoints (admin only)
│   ├── main.py                         # MODIFY — register users router
│   └── schemas/
│       └── auth.py                     # READ ONLY — UserCreateRequest, UserUpdateRequest already defined in M1
├── tests/
│   └── unit/
│       └── test_users_api.py           # CREATE — user management endpoint tests

cast-clone-frontend/
├── lib/
│   ├── api.ts                          # MODIFY — add auth header interceptor + auth API functions
│   ├── types.ts                        # MODIFY — add auth types
│   └── auth-context.tsx                # CREATE — AuthContext provider
├── app/
│   ├── layout.tsx                      # MODIFY — wrap with AuthProvider
│   ├── login/
│   │   └── page.tsx                    # CREATE — login page
│   ├── setup/
│   │   └── page.tsx                    # CREATE — first-run setup page
│   └── settings/
│       └── team/
│           └── page.tsx                # MODIFY — admin user management page (replace placeholder)
├── components/
│   ├── layout/
│   │   ├── TopBar.tsx                  # MODIFY — add UserMenu
│   │   └── UserMenu.tsx               # CREATE — user dropdown menu
│   └── users/
│       ├── UserTable.tsx               # CREATE — user list table
│       └── UserFormDialog.tsx          # CREATE — create/edit user dialog
```

---

## Task 1: Backend — User Management API (Admin Only)

**Files:**
- Create: `cast-clone-backend/app/api/users.py`
- Create: `cast-clone-backend/tests/unit/test_users_api.py`
- Modify: `cast-clone-backend/app/main.py`

- [ ] **Step 1: Write failing tests for user CRUD endpoints**

Create `cast-clone-backend/tests/unit/test_users_api.py`:

```python
"""Tests for user management API endpoints (admin only)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.models.db import User
from app.services.auth import hash_password


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestUserEndpointsExist:
    """Smoke tests to verify endpoints are registered (not 404)."""

    @pytest.mark.asyncio
    async def test_list_users_requires_auth(self, client):
        resp = await client.get("/api/v1/users")
        assert resp.status_code == 401  # no token

    @pytest.mark.asyncio
    async def test_create_user_requires_auth(self, client):
        resp = await client.post("/api/v1/users", json={
            "username": "new", "email": "new@test.com",
            "password": "password123",
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_user_requires_auth(self, client):
        resp = await client.get("/api/v1/users/some-id")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_update_user_requires_auth(self, client):
        resp = await client.put("/api/v1/users/some-id", json={"role": "admin"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_delete_user_requires_auth(self, client):
        resp = await client.delete("/api/v1/users/some-id")
        assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_users_api.py -v`
Expected: FAIL (endpoints not found, 404 instead of 401)

- [ ] **Step 3: Implement user management API**

Create `cast-clone-backend/app/api/users.py`:

```python
"""User management API endpoints — admin only."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.models.db import User
from app.schemas.auth import UserCreateRequest, UserResponse, UserUpdateRequest
from app.services.auth import hash_password
from app.services.postgres import get_session

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
async def list_users(
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> list[UserResponse]:
    """List all users. Admin only."""
    result = await session.execute(
        select(User).order_by(User.created_at.desc())
    )
    users = result.scalars().all()
    return [UserResponse.model_validate(u, from_attributes=True) for u in users]


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    req: UserCreateRequest,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> UserResponse:
    """Create a new user. Admin only."""
    # Check for duplicate username or email
    existing = await session.execute(
        select(User).where(
            (User.username == req.username) | (User.email == req.email)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already exists",
        )

    user = User(
        username=req.username,
        email=req.email,
        password_hash=hash_password(req.password),
        role=req.role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    logger.info("user_created", user_id=user.id, username=user.username, role=user.role)
    return UserResponse.model_validate(user, from_attributes=True)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> UserResponse:
    """Get a user by ID. Admin only."""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(user, from_attributes=True)


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    req: UserUpdateRequest,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_admin),
) -> UserResponse:
    """Update a user. Admin only."""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if req.username is not None:
        # Check uniqueness
        dup = await session.execute(
            select(User).where(User.username == req.username, User.id != user_id)
        )
        if dup.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Username already taken")
        user.username = req.username

    if req.email is not None:
        dup = await session.execute(
            select(User).where(User.email == req.email, User.id != user_id)
        )
        if dup.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email already taken")
        user.email = req.email

    if req.password is not None:
        user.password_hash = hash_password(req.password)

    if req.role is not None:
        user.role = req.role

    if req.is_active is not None:
        user.is_active = req.is_active

    await session.commit()
    await session.refresh(user)

    logger.info("user_updated", user_id=user.id, username=user.username)
    return UserResponse.model_validate(user, from_attributes=True)


@router.delete("/{user_id}", status_code=204)
async def deactivate_user(
    user_id: str,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
) -> None:
    """Deactivate a user (soft delete). Admin only.

    Admins cannot deactivate themselves.
    """
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate yourself",
        )

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    await session.commit()

    logger.info("user_deactivated", user_id=user.id, username=user.username)
```

- [ ] **Step 4: Register users router via api/__init__.py and main.py**

Add to `cast-clone-backend/app/api/__init__.py`:

```python
from app.api.users import router as users_router
```

And add `"users_router"` to the `__all__` list.

Then add `users_router` to the import block in `cast-clone-backend/app/main.py` and register with:

```python
app.include_router(users_router)
```

- [ ] **Step 5: Run tests to verify endpoints are registered**

Run: `cd cast-clone-backend && uv run pytest tests/unit/test_users_api.py -v`
Expected: All 5 tests pass (401 responses, not 404)

- [ ] **Step 6: Commit**

```bash
git add cast-clone-backend/app/api/users.py cast-clone-backend/app/main.py cast-clone-backend/tests/unit/test_users_api.py
git commit -m "feat(auth): add user management CRUD API endpoints (admin only)"
```

---

## Task 2: Frontend — Auth Types and API Client

**Files:**
- Modify: `cast-clone-frontend/lib/types.ts`
- Modify: `cast-clone-frontend/lib/api.ts`

- [ ] **Step 1: Add auth types to types.ts**

Add to `cast-clone-frontend/lib/types.ts`:

```typescript
// ── Phase 4: Auth & User Management ──

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
}

export interface UserResponse {
  id: string;
  username: string;
  email: string;
  role: "admin" | "member";
  is_active: boolean;
  created_at: string;
  last_login: string | null;
}

export interface SetupStatusResponse {
  needs_setup: boolean;
}

export interface SetupRequest {
  username: string;
  email: string;
  password: string;
}

export interface UserCreateRequest {
  username: string;
  email: string;
  password: string;
  role?: "admin" | "member";
}

export interface UserUpdateRequest {
  username?: string;
  email?: string;
  password?: string;
  role?: "admin" | "member";
  is_active?: boolean;
}
```

- [ ] **Step 2: Add auth interceptor and auth API functions to api.ts**

Modify `cast-clone-frontend/lib/api.ts`. Add a token getter at the top:

```typescript
function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("auth_token");
}
```

Modify the `apiFetch` function to include the Authorization header when a token exists. In the headers construction, add:

```typescript
const token = getAuthToken();
if (token) {
  headers["Authorization"] = `Bearer ${token}`;
}
```

Add auth API functions at the bottom:

```typescript
// ── Auth ──

export async function login(
  username: string,
  password: string
): Promise<LoginResponse> {
  // Login uses form-encoded data, not JSON
  const resp = await fetch(`${BASE_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username, password }),
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new ApiError(resp.status, body.detail || "Login failed");
  }
  return resp.json();
}

export async function getMe(): Promise<UserResponse> {
  return apiFetch<UserResponse>("/api/v1/auth/me");
}

export async function getSetupStatus(): Promise<SetupStatusResponse> {
  return apiFetch<SetupStatusResponse>("/api/v1/auth/setup-status");
}

export async function initialSetup(req: SetupRequest): Promise<UserResponse> {
  return apiFetch<UserResponse>("/api/v1/auth/setup", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

// ── User Management (Admin) ──

export async function listUsers(): Promise<UserResponse[]> {
  return apiFetch<UserResponse[]>("/api/v1/users");
}

export async function createUser(req: UserCreateRequest): Promise<UserResponse> {
  return apiFetch<UserResponse>("/api/v1/users", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function getUser(userId: string): Promise<UserResponse> {
  return apiFetch<UserResponse>(`/api/v1/users/${userId}`);
}

export async function updateUser(
  userId: string,
  req: UserUpdateRequest
): Promise<UserResponse> {
  return apiFetch<UserResponse>(`/api/v1/users/${userId}`, {
    method: "PUT",
    body: JSON.stringify(req),
  });
}

export async function deactivateUser(userId: string): Promise<void> {
  await apiFetch<void>(`/api/v1/users/${userId}`, { method: "DELETE" });
}
```

- [ ] **Step 3: Verify types compile**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add cast-clone-frontend/lib/types.ts cast-clone-frontend/lib/api.ts
git commit -m "feat(auth): add auth types and API client with token interceptor"
```

---

## Task 3: Frontend — AuthContext Provider

**Files:**
- Create: `cast-clone-frontend/lib/auth-context.tsx`
- Modify: `cast-clone-frontend/app/layout.tsx`

- [ ] **Step 1: Create AuthContext provider**

Create `cast-clone-frontend/lib/auth-context.tsx`:

```tsx
"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
import { useRouter, usePathname } from "next/navigation";
import type { UserResponse } from "./types";
import { getMe, getSetupStatus, login as apiLogin } from "./api";

interface AuthContextValue {
  user: UserResponse | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/** Public routes that don't require authentication. */
const PUBLIC_PATHS = ["/login", "/setup"];

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  const isPublicPath = PUBLIC_PATHS.some((p) => pathname.startsWith(p));

  // On mount: check if we need setup, then validate existing token
  useEffect(() => {
    let cancelled = false;

    async function init() {
      try {
        // Check if system needs initial setup
        const { needs_setup } = await getSetupStatus();
        if (needs_setup) {
          if (!cancelled) {
            setIsLoading(false);
            if (pathname !== "/setup") router.replace("/setup");
          }
          return;
        }

        // Try to load user from existing token
        const token = localStorage.getItem("auth_token");
        if (!token) {
          if (!cancelled) {
            setIsLoading(false);
            if (!isPublicPath) router.replace("/login");
          }
          return;
        }

        const me = await getMe();
        if (!cancelled) setUser(me);
      } catch {
        // Token invalid or expired
        localStorage.removeItem("auth_token");
        if (!cancelled && !isPublicPath) router.replace("/login");
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    init();
    return () => {
      cancelled = true;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const loginFn = useCallback(
    async (username: string, password: string) => {
      const { access_token } = await apiLogin(username, password);
      localStorage.setItem("auth_token", access_token);
      const me = await getMe();
      setUser(me);
      router.replace("/");
    },
    [router]
  );

  const logout = useCallback(() => {
    localStorage.removeItem("auth_token");
    setUser(null);
    router.replace("/login");
  }, [router]);

  const value = useMemo(
    () => ({
      user,
      isLoading,
      isAuthenticated: !!user,
      login: loginFn,
      logout,
    }),
    [user, isLoading, loginFn, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
```

- [ ] **Step 2: Wrap app with AuthProvider in layout.tsx**

Modify `cast-clone-frontend/app/layout.tsx`. Import `AuthProvider`:

```tsx
import { AuthProvider } from "@/lib/auth-context";
```

Wrap the children inside `ThemeProvider` with `AuthProvider`:

```tsx
<ThemeProvider ...>
  <AuthProvider>
    <GlobalShell>{children}</GlobalShell>
  </AuthProvider>
</ThemeProvider>
```

- [ ] **Step 3: Verify types compile**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add cast-clone-frontend/lib/auth-context.tsx cast-clone-frontend/app/layout.tsx
git commit -m "feat(auth): add AuthContext provider with token persistence and route guards"
```

---

## Task 4: Frontend — Login Page

**Files:**
- Create: `cast-clone-frontend/app/login/page.tsx`

- [ ] **Step 1: Create login page**

Create `cast-clone-frontend/app/login/page.tsx`:

```tsx
"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Network } from "lucide-react";

export default function LoginPage() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(username, password);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Login failed";
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10">
            <Network className="h-6 w-6 text-primary" />
          </div>
          <CardTitle className="text-2xl">CodeLens</CardTitle>
          <CardDescription>
            Sign in to access your architecture intelligence platform
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                {error}
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Enter your username"
                autoComplete="username"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your password"
                autoComplete="current-password"
                required
              />
            </div>
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "Signing in..." : "Sign in"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: Verify types compile**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add cast-clone-frontend/app/login/page.tsx
git commit -m "feat(auth): add login page with form and error handling"
```

---

## Task 5: Frontend — First-Run Setup Page

**Files:**
- Create: `cast-clone-frontend/app/setup/page.tsx`

- [ ] **Step 1: Create setup page**

Create `cast-clone-frontend/app/setup/page.tsx`:

```tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { initialSetup } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Network, ShieldCheck } from "lucide-react";

export default function SetupPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    setLoading(true);
    try {
      await initialSetup({ username, email, password });
      router.replace("/login");
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Setup failed";
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10">
            <Network className="h-6 w-6 text-primary" />
          </div>
          <CardTitle className="text-2xl">Welcome to CodeLens</CardTitle>
          <CardDescription>
            Create the initial administrator account to get started
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                {error}
              </div>
            )}
            <div className="flex items-center gap-2 rounded-md bg-muted p-3 text-sm text-muted-foreground">
              <ShieldCheck className="h-4 w-4 shrink-0" />
              <span>This account will have administrator privileges</span>
            </div>
            <div className="space-y-2">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="admin"
                autoComplete="username"
                required
                minLength={3}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@example.com"
                autoComplete="email"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Minimum 8 characters"
                autoComplete="new-password"
                required
                minLength={8}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirm-password">Confirm Password</Label>
              <Input
                id="confirm-password"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Re-enter password"
                autoComplete="new-password"
                required
                minLength={8}
              />
            </div>
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "Creating account..." : "Create Admin Account"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: Verify types compile**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add cast-clone-frontend/app/setup/page.tsx
git commit -m "feat(auth): add first-run setup page for initial admin account"
```

---

## Task 6: Frontend — UserMenu Component

**Files:**
- Create: `cast-clone-frontend/components/layout/UserMenu.tsx`
- Modify: `cast-clone-frontend/components/layout/TopBar.tsx`

- [ ] **Step 1: Create UserMenu component**

Create `cast-clone-frontend/components/layout/UserMenu.tsx`:

```tsx
"use client";

import { useState, useRef, useEffect } from "react";
import { useAuth } from "@/lib/auth-context";
import { User, LogOut, Shield } from "lucide-react";
import { Button } from "@/components/ui/button";

export function UserMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  if (!user) return null;

  return (
    <div className="relative" ref={menuRef}>
      <Button
        variant="ghost"
        size="sm"
        className="flex items-center gap-1.5 px-2"
        onClick={() => setOpen(!open)}
      >
        <User className="h-4 w-4" />
        <span className="hidden text-xs sm:inline">{user.username}</span>
        {user.role === "admin" && (
          <Shield className="h-3 w-3 text-amber-500" />
        )}
      </Button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 w-56 rounded-md border bg-popover p-1 shadow-md">
          <div className="px-3 py-2 text-sm">
            <p className="font-medium">{user.username}</p>
            <p className="text-xs text-muted-foreground">{user.email}</p>
            <p className="text-xs text-muted-foreground capitalize">
              {user.role}
            </p>
          </div>
          <div className="h-px bg-border" />
          <button
            className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-sm text-destructive hover:bg-accent"
            onClick={() => {
              setOpen(false);
              logout();
            }}
          >
            <LogOut className="h-4 w-4" />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add UserMenu to TopBar**

Modify `cast-clone-frontend/components/layout/TopBar.tsx`. Import and add `UserMenu` next to the theme toggle on the right side:

```tsx
import { UserMenu } from "./UserMenu";
```

In the right-side section of TopBar (where the theme toggle button is), add `<UserMenu />` before or after the theme toggle.

- [ ] **Step 3: Verify types compile**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add cast-clone-frontend/components/layout/UserMenu.tsx cast-clone-frontend/components/layout/TopBar.tsx
git commit -m "feat(auth): add UserMenu dropdown to TopBar with profile info and logout"
```

---

## Task 7: Frontend — Admin User Management Page

**Files:**
- Create: `cast-clone-frontend/components/users/UserTable.tsx`
- Create: `cast-clone-frontend/components/users/UserFormDialog.tsx`
- Modify: `cast-clone-frontend/app/settings/team/page.tsx`

- [ ] **Step 1: Create UserTable component**

Create `cast-clone-frontend/components/users/UserTable.tsx`:

```tsx
"use client";

import type { UserResponse } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Shield, UserX } from "lucide-react";

interface UserTableProps {
  users: UserResponse[];
  currentUserId: string;
  onEdit: (user: UserResponse) => void;
  onDeactivate: (user: UserResponse) => void;
}

export function UserTable({
  users,
  currentUserId,
  onEdit,
  onDeactivate,
}: UserTableProps) {
  return (
    <div className="rounded-md border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b bg-muted/50">
            <th className="px-4 py-2 text-left font-medium">Username</th>
            <th className="px-4 py-2 text-left font-medium">Email</th>
            <th className="px-4 py-2 text-left font-medium">Role</th>
            <th className="px-4 py-2 text-left font-medium">Status</th>
            <th className="px-4 py-2 text-left font-medium">Last Login</th>
            <th className="px-4 py-2 text-right font-medium">Actions</th>
          </tr>
        </thead>
        <tbody>
          {users.map((user) => (
            <tr key={user.id} className="border-b last:border-0">
              <td className="px-4 py-2 font-medium">
                <span className="flex items-center gap-1.5">
                  {user.username}
                  {user.id === currentUserId && (
                    <Badge variant="outline" className="text-xs">
                      you
                    </Badge>
                  )}
                </span>
              </td>
              <td className="px-4 py-2 text-muted-foreground">{user.email}</td>
              <td className="px-4 py-2">
                <Badge
                  variant={user.role === "admin" ? "default" : "secondary"}
                  className="gap-1"
                >
                  {user.role === "admin" && <Shield className="h-3 w-3" />}
                  {user.role}
                </Badge>
              </td>
              <td className="px-4 py-2">
                <Badge variant={user.is_active ? "outline" : "destructive"}>
                  {user.is_active ? "Active" : "Inactive"}
                </Badge>
              </td>
              <td className="px-4 py-2 text-muted-foreground text-xs">
                {user.last_login
                  ? new Date(user.last_login).toLocaleDateString()
                  : "Never"}
              </td>
              <td className="px-4 py-2 text-right">
                <div className="flex items-center justify-end gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => onEdit(user)}
                  >
                    Edit
                  </Button>
                  {user.id !== currentUserId && user.is_active && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-destructive"
                      onClick={() => onDeactivate(user)}
                    >
                      <UserX className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 2: Create UserFormDialog component**

Create `cast-clone-frontend/components/users/UserFormDialog.tsx`:

```tsx
"use client";

import { useState, useEffect } from "react";
import type { UserResponse, UserCreateRequest, UserUpdateRequest } from "@/lib/types";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface UserFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editUser: UserResponse | null;
  onSave: (data: UserCreateRequest | UserUpdateRequest) => Promise<void>;
}

export function UserFormDialog({
  open,
  onOpenChange,
  editUser,
  onSave,
}: UserFormDialogProps) {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"admin" | "member">("member");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const isEdit = !!editUser;

  useEffect(() => {
    if (editUser) {
      setUsername(editUser.username);
      setEmail(editUser.email);
      setRole(editUser.role);
      setPassword("");
    } else {
      setUsername("");
      setEmail("");
      setPassword("");
      setRole("member");
    }
    setError("");
  }, [editUser, open]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      if (isEdit) {
        const update: UserUpdateRequest = {};
        if (username !== editUser.username) update.username = username;
        if (email !== editUser.email) update.email = email;
        if (password) update.password = password;
        if (role !== editUser.role) update.role = role;
        await onSave(update);
      } else {
        await onSave({ username, email, password, role });
      }
      onOpenChange(false);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save user");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit User" : "Create User"}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}
          <div className="space-y-2">
            <Label htmlFor="username">Username</Label>
            <Input
              id="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              minLength={3}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">
              Password{isEdit ? " (leave blank to keep)" : ""}
            </Label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required={!isEdit}
              minLength={8}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="role">Role</Label>
            <select
              id="role"
              value={role}
              onChange={(e) => setRole(e.target.value as "admin" | "member")}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
            >
              <option value="member">Member</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? "Saving..." : isEdit ? "Update" : "Create"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 3: Replace team settings page with user management**

Replace the content of `cast-clone-frontend/app/settings/team/page.tsx` with:

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import {
  listUsers,
  createUser,
  updateUser,
  deactivateUser,
} from "@/lib/api";
import type { UserResponse, UserCreateRequest, UserUpdateRequest } from "@/lib/types";
import { UserTable } from "@/components/users/UserTable";
import { UserFormDialog } from "@/components/users/UserFormDialog";
import { Button } from "@/components/ui/button";
import { UserPlus } from "lucide-react";

export default function TeamSettingsPage() {
  const { user } = useAuth();
  const [users, setUsers] = useState<UserResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<UserResponse | null>(null);

  const loadUsers = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listUsers();
      setUsers(data);
    } catch {
      // User may not be admin — silently fail
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadUsers();
  }, [loadUsers]);

  function handleCreate() {
    setEditTarget(null);
    setDialogOpen(true);
  }

  function handleEdit(u: UserResponse) {
    setEditTarget(u);
    setDialogOpen(true);
  }

  async function handleDeactivate(u: UserResponse) {
    if (!confirm(`Deactivate user "${u.username}"? They will no longer be able to sign in.`)) {
      return;
    }
    await deactivateUser(u.id);
    await loadUsers();
  }

  async function handleSave(data: UserCreateRequest | UserUpdateRequest) {
    if (editTarget) {
      await updateUser(editTarget.id, data as UserUpdateRequest);
    } else {
      await createUser(data as UserCreateRequest);
    }
    await loadUsers();
  }

  if (!user || user.role !== "admin") {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        Admin access required
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Team Management</h1>
          <p className="text-sm text-muted-foreground">
            Manage user accounts and roles
          </p>
        </div>
        <Button onClick={handleCreate} className="gap-1.5">
          <UserPlus className="h-4 w-4" />
          Add User
        </Button>
      </div>

      {loading ? (
        <div className="text-center text-muted-foreground py-8">Loading...</div>
      ) : (
        <UserTable
          users={users}
          currentUserId={user.id}
          onEdit={handleEdit}
          onDeactivate={handleDeactivate}
        />
      )}

      <UserFormDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        editUser={editTarget}
        onSave={handleSave}
      />
    </div>
  );
}
```

- [ ] **Step 4: Verify types compile**

Run: `cd cast-clone-frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add cast-clone-frontend/components/users/UserTable.tsx cast-clone-frontend/components/users/UserFormDialog.tsx cast-clone-frontend/app/settings/team/page.tsx
git commit -m "feat(auth): add admin user management page with user table and form dialog"
```

---

## Verification Checklist

- [ ] Backend: `POST /api/v1/users` creates users (admin only, returns 401 without token)
- [ ] Backend: `GET /api/v1/users` lists users (admin only)
- [ ] Backend: `PUT /api/v1/users/{id}` updates users
- [ ] Backend: `DELETE /api/v1/users/{id}` deactivates users (cannot deactivate self)
- [ ] Frontend: `lib/api.ts` adds Authorization header from localStorage token
- [ ] Frontend: `lib/auth-context.tsx` provides user state, login, logout, setup redirect
- [ ] Frontend: `/login` page with username/password form
- [ ] Frontend: `/setup` page for first-run admin creation
- [ ] Frontend: `UserMenu` in TopBar shows username, role, and logout
- [ ] Frontend: `/settings/team` page with user table, create/edit dialog, deactivate
- [ ] `npx tsc --noEmit` passes with no errors
- [ ] `uv run pytest tests/unit/test_users_api.py -v` passes
- [ ] `uv run ruff check app/api/users.py` passes
