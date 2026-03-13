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
      // User may not be admin
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
