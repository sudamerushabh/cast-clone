"use client";

import { useState } from "react";
import type { TagResponse, TagName } from "@/lib/types";
import { PREDEFINED_TAGS } from "@/lib/types";
import { useAuth } from "@/lib/auth-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Plus, X } from "lucide-react";

const TAG_COLORS: Record<string, string> = {
  deprecated: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  "tech-debt": "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  "critical-path": "bg-violet-100 text-violet-800 dark:bg-violet-900 dark:text-violet-200",
  "security-sensitive": "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
  "needs-review": "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
};

interface TagBadgesProps {
  tags: TagResponse[];
  onAdd: (tagName: TagName) => Promise<void>;
  onRemove: (tagId: string) => Promise<void>;
}

export function TagBadges({ tags, onAdd, onRemove }: TagBadgesProps) {
  const { user } = useAuth();
  const [showPicker, setShowPicker] = useState(false);
  const existingNames = new Set(tags.map((t) => t.tag_name));

  const availableTags = PREDEFINED_TAGS.filter((t) => !existingNames.has(t));

  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap gap-1">
        {tags.map((tag) => (
          <Badge
            key={tag.id}
            variant="secondary"
            className={`gap-1 text-xs ${TAG_COLORS[tag.tag_name] ?? ""}`}
          >
            {tag.tag_name}
            {(user?.id === tag.author.id || user?.role === "admin") && (
              <button
                className="ml-0.5 hover:text-destructive"
                onClick={() => onRemove(tag.id)}
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </Badge>
        ))}

        {availableTags.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            className="h-5 px-1"
            onClick={() => setShowPicker(!showPicker)}
          >
            <Plus className="h-3 w-3" />
          </Button>
        )}
      </div>

      {showPicker && availableTags.length > 0 && (
        <div className="flex flex-wrap gap-1 rounded-md border p-1.5">
          {availableTags.map((tagName) => (
            <Badge
              key={tagName}
              variant="outline"
              className={`cursor-pointer text-xs hover:opacity-80 ${TAG_COLORS[tagName] ?? ""}`}
              onClick={async () => {
                await onAdd(tagName);
                setShowPicker(false);
              }}
            >
              + {tagName}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
