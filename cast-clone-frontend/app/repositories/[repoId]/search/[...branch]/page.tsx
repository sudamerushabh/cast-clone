export default async function BranchSearchPage({
  params,
}: {
  params: Promise<{ repoId: string; branch: string[] }>;
}) {
  const { repoId, branch } = await params;
  const branchName = branch.join("/");
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold">Search</h1>
      <p className="mt-1 text-muted-foreground">
        Search symbols for {repoId} / {decodeURIComponent(branchName)}.
      </p>
    </div>
  );
}
