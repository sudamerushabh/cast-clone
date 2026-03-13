"use client";

import { useState } from "react";
import type { AnnotationResponse } from "@/lib/types";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import { Pencil, Trash2, X, Check } from "lucide-react";

interface AnnotationListProps {
  annotations: AnnotationResponse[];
  onEdit: (id: string, content: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

export function AnnotationList({
  annotations,
  onEdit,
  onDelete,
}: AnnotationListProps) {
  const { user } = useAuth();
  const [editId, setEditId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");

  if (annotations.length === 0) {
    return (
      <p className="text-xs text-muted-foreground py-1">No annotations yet</p>
    );
  }

  return (
    <div className="space-y-2">
      {annotations.map((ann) => (
        <div
          key={ann.id}
          className="rounded-md border p-2 text-sm space-y-1"
        >
          {editId === ann.id ? (
            <div className="space-y-1">
              <textarea
                className="w-full rounded border bg-background px-2 py-1 text-sm"
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                rows={2}
              />
              <div className="flex gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 w-6 p-0"
                  onClick={async () => {
                    await onEdit(ann.id, editContent);
                    setEditId(null);
                  }}
                >
                  <Check className="h-3 w-3" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 w-6 p-0"
                  onClick={() => setEditId(null)}
                >
                  <X className="h-3 w-3" />
                </Button>
              </div>
            </div>
          ) : (
            <>
              <p>{ann.content}</p>
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>
                  {ann.author.username} &middot;{" "}
                  {new Date(ann.created_at).toLocaleDateString()}
                </span>
                {(user?.id === ann.author.id || user?.role === "admin") && (
                  <div className="flex gap-0.5">
                    {user?.id === ann.author.id && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-5 w-5 p-0"
                        onClick={() => {
                          setEditId(ann.id);
                          setEditContent(ann.content);
                        }}
                      >
                        <Pencil className="h-3 w-3" />
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-5 w-5 p-0 text-destructive"
                      onClick={() => onDelete(ann.id)}
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      ))}
    </div>
  );
}
