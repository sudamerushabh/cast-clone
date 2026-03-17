// app/repositories/[repoId]/[...branch]/layout.tsx
// ChatProvider is now in the parent [repoId]/layout.tsx
export default function BranchLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
