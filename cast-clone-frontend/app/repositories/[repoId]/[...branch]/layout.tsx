// app/repositories/[repoId]/[...branch]/layout.tsx
"use client";

import { useParams } from "next/navigation";
import { useRepoProject } from "@/hooks/useRepoProject";
import { ChatProvider } from "@/components/chat/ChatProvider";
import { ChatDrawer } from "@/components/chat/ChatDrawer";

export default function BranchLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams();
  const repoId = params.repoId as string;
  const branchSegments = params.branch as string[];
  const branchName = branchSegments
    ?.map(decodeURIComponent)
    .join("/") ?? "main";

  const { projectId } = useRepoProject(repoId, branchName);

  // If projectId isn't resolved yet, render without chat
  // (the page components handle their own loading states)
  if (!projectId) {
    return <>{children}</>;
  }

  return (
    <ChatProvider projectId={projectId} projectName={branchName}>
      {children}
      <ChatDrawer projectName={branchName} />
    </ChatProvider>
  );
}
