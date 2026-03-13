"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { fetchGitConfig } from "@/lib/api";
import { GitIntegrationForm } from "@/components/pull-requests/GitIntegrationForm";
import type { GitConfig } from "@/lib/types";

export default function GitIntegrationPage() {
  const params = useParams();
  const projectId = params.id as string;
  const [config, setConfig] = useState<GitConfig | null | undefined>(undefined);

  const loadConfig = async () => {
    const cfg = await fetchGitConfig(projectId);
    setConfig(cfg);
  };

  useEffect(() => {
    loadConfig();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  if (config === undefined) {
    return <div className="p-6 text-gray-500">Loading...</div>;
  }

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">
        Git Integration
      </h1>
      <GitIntegrationForm
        projectId={projectId}
        existing={config}
        onSaved={loadConfig}
      />
    </div>
  );
}
