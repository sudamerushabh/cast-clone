"use client";
import * as React from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";

interface BranchPickerProps {
  branches: string[];
  defaultBranch: string;
  selected: string[];
  onChange: (selected: string[]) => void;
}

export function BranchPicker({ branches, defaultBranch, selected, onChange }: BranchPickerProps) {
  function toggle(branch: string) {
    if (selected.includes(branch)) {
      onChange(selected.filter((b) => b !== branch));
    } else {
      onChange([...selected, branch]);
    }
  }

  return (
    <div className="space-y-2">
      {branches.map((branch) => (
        <div key={branch} className="flex items-center gap-2">
          <Checkbox id={`branch-${branch}`} checked={selected.includes(branch)} onCheckedChange={() => toggle(branch)} />
          <Label htmlFor={`branch-${branch}`} className="text-sm">
            {branch}
            {branch === defaultBranch && <span className="ml-1.5 text-xs text-muted-foreground">(default)</span>}
          </Label>
        </div>
      ))}
    </div>
  );
}
