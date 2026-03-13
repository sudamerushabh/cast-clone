"use client"

import { useParams } from "next/navigation"
import { GraphExplorer } from "@/components/graph/GraphExplorer"

export default function GraphPage() {
  const params = useParams<{ id: string }>()
  return <GraphExplorer projectId={params.id} />
}
