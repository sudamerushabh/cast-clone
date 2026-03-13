"use client";

import { useCallback, useState } from "react";
import type { AnnotationResponse, TagResponse, TagName } from "@/lib/types";
import {
  createAnnotation,
  listAnnotations,
  updateAnnotation,
  deleteAnnotation,
  addTag,
  listTags,
  deleteTag,
} from "@/lib/api";

interface UseAnnotationsResult {
  annotations: AnnotationResponse[];
  tags: TagResponse[];
  loading: boolean;
  loadForNode: (projectId: string, nodeFqn: string) => Promise<void>;
  addAnnotation: (
    projectId: string,
    nodeFqn: string,
    content: string
  ) => Promise<void>;
  editAnnotation: (annotationId: string, content: string) => Promise<void>;
  removeAnnotation: (annotationId: string) => Promise<void>;
  addNodeTag: (
    projectId: string,
    nodeFqn: string,
    tagName: TagName
  ) => Promise<void>;
  removeTag: (tagId: string) => Promise<void>;
}

export function useAnnotations(): UseAnnotationsResult {
  const [annotations, setAnnotations] = useState<AnnotationResponse[]>([]);
  const [tags, setTags] = useState<TagResponse[]>([]);
  const [loading, setLoading] = useState(false);

  const loadForNode = useCallback(
    async (projectId: string, nodeFqn: string) => {
      setLoading(true);
      try {
        const [anns, tgs] = await Promise.all([
          listAnnotations(projectId, nodeFqn),
          listTags(projectId, { node_fqn: nodeFqn }),
        ]);
        setAnnotations(anns);
        setTags(tgs);
      } catch {
        setAnnotations([]);
        setTags([]);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const addAnnotationFn = useCallback(
    async (projectId: string, nodeFqn: string, content: string) => {
      const ann = await createAnnotation(projectId, nodeFqn, content);
      setAnnotations((prev) => [ann, ...prev]);
    },
    []
  );

  const editAnnotation = useCallback(
    async (annotationId: string, content: string) => {
      const updated = await updateAnnotation(annotationId, content);
      setAnnotations((prev) =>
        prev.map((a) => (a.id === annotationId ? updated : a))
      );
    },
    []
  );

  const removeAnnotation = useCallback(async (annotationId: string) => {
    await deleteAnnotation(annotationId);
    setAnnotations((prev) => prev.filter((a) => a.id !== annotationId));
  }, []);

  const addNodeTag = useCallback(
    async (projectId: string, nodeFqn: string, tagName: TagName) => {
      const tag = await addTag(projectId, nodeFqn, tagName);
      setTags((prev) => [tag, ...prev]);
    },
    []
  );

  const removeTagFn = useCallback(async (tagId: string) => {
    await deleteTag(tagId);
    setTags((prev) => prev.filter((t) => t.id !== tagId));
  }, []);

  return {
    annotations,
    tags,
    loading,
    loadForNode,
    addAnnotation: addAnnotationFn,
    editAnnotation,
    removeAnnotation,
    addNodeTag,
    removeTag: removeTagFn,
  };
}
