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
