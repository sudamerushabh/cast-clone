export default async function BranchOverviewPage({
  params,
}: {
  params: Promise<{ repoId: string; branch: string[] }>;
}) {
  const { repoId, branch } = await params;
  const branchName = branch.join("/");
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold">
        {decodeURIComponent(branchName)}
      </h1>
      <p className="mt-1 text-muted-foreground">
        Project overview for repository {repoId}, branch{" "}
        {decodeURIComponent(branchName)}.
      </p>
    </div>
  );
}
