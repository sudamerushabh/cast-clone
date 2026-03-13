"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { MessageSquarePlus } from "lucide-react";

interface AddAnnotationProps {
  onAdd: (content: string) => Promise<void>;
}

export function AddAnnotation({ onAdd }: AddAnnotationProps) {
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!content.trim()) return;
    setLoading(true);
    try {
      await onAdd(content.trim());
      setContent("");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex gap-1.5">
      <input
        className="flex-1 rounded-md border bg-background px-2 py-1 text-sm"
        placeholder="Add a note..."
        value={content}
        onChange={(e) => setContent(e.target.value)}
      />
      <Button
        type="submit"
        variant="ghost"
        size="sm"
        disabled={loading || !content.trim()}
        className="shrink-0"
      >
        <MessageSquarePlus className="h-4 w-4" />
      </Button>
    </form>
  );
}
