export default async function BranchChatPage({
  params,
}: {
  params: Promise<{ repoId: string; branch: string[] }>;
}) {
  const { repoId, branch } = await params;
  const branchName = branch.join("/");
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold">AI Assistant</h1>
      <p className="mt-1 text-muted-foreground">
        AI assistant for {repoId} / {decodeURIComponent(branchName)}.
      </p>
    </div>
  );
}
