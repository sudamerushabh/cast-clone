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
