import Image from "next/image";
import { cn } from "@/lib/utils";
import type { ConnectorProvider } from "@/lib/types";

interface ProviderLogoProps {
  provider: ConnectorProvider;
  size?: number;
  className?: string;
  style?: React.CSSProperties;
}

const providerMeta: Record<
  ConnectorProvider,
  { label: string; logo: string; color: string }
> = {
  github: { label: "GitHub", logo: "/logos/github.svg", color: "#24292f" },
  gitlab: { label: "GitLab", logo: "/logos/gitlab.svg", color: "#FC6D26" },
  gitea: { label: "Gitea", logo: "/logos/gitea.svg", color: "#609926" },
  bitbucket: {
    label: "Bitbucket",
    logo: "/logos/bitbucket.svg",
    color: "#0052CC",
  },
};

export function ProviderLogo({
  provider,
  size = 24,
  className,
  style,
}: ProviderLogoProps) {
  const meta = providerMeta[provider];
  return (
    <Image
      src={meta.logo}
      alt={meta.label}
      width={size}
      height={size}
      className={cn("dark:invert", className)}
      style={style}
    />
  );
}

export { providerMeta };
