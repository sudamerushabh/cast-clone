"use client";

import { useCallback, useState } from "react";
import type { SavedViewListItem, SavedViewResponse } from "@/lib/types";
import { saveView, listViews, getView, deleteView } from "@/lib/api";

interface UseSavedViewsResult {
  views: SavedViewListItem[];
  loading: boolean;
  loadViews: (projectId: string) => Promise<void>;
  save: (
    projectId: string,
    name: string,
    state: Record<string, unknown>,
    description?: string
  ) => Promise<SavedViewResponse>;
  load: (viewId: string) => Promise<SavedViewResponse>;
  remove: (viewId: string) => Promise<void>;
}

export function useSavedViews(): UseSavedViewsResult {
  const [views, setViews] = useState<SavedViewListItem[]>([]);
  const [loading, setLoading] = useState(false);

  const loadViews = useCallback(async (projectId: string) => {
    setLoading(true);
    try {
      const data = await listViews(projectId);
      setViews(data);
    } catch {
      setViews([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const save = useCallback(
    async (
      projectId: string,
      name: string,
      state: Record<string, unknown>,
      description?: string
    ) => {
      const view = await saveView(projectId, name, state, description);
      setViews((prev) => [
        {
          id: view.id,
          project_id: view.project_id,
          name: view.name,
          description: view.description,
          author: view.author,
          created_at: view.created_at,
          updated_at: view.updated_at,
        },
        ...prev,
      ]);
      return view;
    },
    []
  );

  const load = useCallback(async (viewId: string) => {
    return getView(viewId);
  }, []);

  const remove = useCallback(async (viewId: string) => {
    await deleteView(viewId);
    setViews((prev) => prev.filter((v) => v.id !== viewId));
  }, []);

  return { views, loading, loadViews, save, load, remove };
}
