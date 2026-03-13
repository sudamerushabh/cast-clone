export default async function RepoDetailPage({
  params,
}: {
  params: Promise<{ repoId: string }>;
}) {
  const { repoId } = await params;
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold">Repository: {repoId}</h1>
      <p className="mt-2 text-muted-foreground">
        Branches and analysis history will appear here.
      </p>
    </div>
  );
}
