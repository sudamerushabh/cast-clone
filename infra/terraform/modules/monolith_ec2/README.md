# Module: `cast-clone-monolith-ec2`

Single EC2 instance running the full cast-clone stack (Postgres, Neo4j Community, Redis, MinIO, backend, frontend, MCP, Caddy reverse-proxy with self-signed TLS) via Docker Compose. All persistent data lives on a separate EBS volume mounted at `/var/lib/cast-clone`.

Used by **T1 Starter** today; the same module backs the Marketplace AMI Quick Launch in step 3.

## What gets created

| Resource | Purpose |
|---|---|
| `aws_security_group` + ingress rules | 443 from `allow_https_from_cidrs`, optional 22 from `allow_ssh_from_cidrs`, all egress |
| `aws_instance` | Application host. Uses latest AL2023 by default; Marketplace passes a published AMI ID. |
| `aws_ebs_volume` (gp3) | Data volume. Tagged `CastCloneBackup=true` for AWS Backup selection. |
| `aws_volume_attachment` | Attaches data volume at `/dev/sdf` (presents as `/dev/nvme1n1` on Nitro instances). |
| `aws_eip` (optional) | Stable public IP across stop/start cycles. |

## What user-data does (runs once via cloud-init)

1. Installs Docker + the Compose v2 plugin.
2. Locates the EBS data volume (first non-root NVMe disk), formats it XFS if blank, adds an `/etc/fstab` entry, mounts it at `/var/lib/cast-clone`.
3. Generates a self-signed RSA-4096 cert valid 10 years. Subject Alt Name covers the EC2 public IP.
4. Fetches Postgres password, Neo4j password, license JWT, and (optionally) Anthropic / OpenAI API keys from Secrets Manager.
5. Records `first_boot_at` to `/var/lib/cast-clone/license-state.json` — the trial-license clock anchor.
6. Writes `/opt/cast-clone/.env` with secret values; writes `docker-compose.yml` and `Caddyfile` from Terraform-rendered templates.
7. Logs in to ECR if the registry hostname matches the ECR pattern (best-effort; no-op for public registries or pre-pulled images).
8. `docker compose pull && docker compose up -d`.
9. Installs a `cast-clone.service` systemd unit so containers restart on reboot.

User-data only runs on the *first* boot. The fstab entry handles mounting on subsequent boots; the systemd unit handles container start. Re-running user-data requires `cloud-init clean && cloud-init init` from inside the instance, or recreating the instance.

## Trial license precedence

The application reads its license at startup with the following preference:

1. `LICENSE_JWT` env var from `.env` (sourced from Secrets Manager).
2. If `LICENSE_JWT == "TRIAL_PLACEHOLDER"`, a baked-in trial JWT (Marketplace AMI build step) is used. The 14-day clock starts at `first_boot_at` from `/var/lib/cast-clone/license-state.json`, not at the JWT's `exp`. This prevents customers with old AMIs from getting truncated trials.
3. After purchase, the customer updates the `<name_prefix>/license/jwt` Secrets Manager value with the production JWT and runs `systemctl restart cast-clone.service`.

## Self-signed cert UX

First visit shows a browser certificate warning. This is expected for T1 starter. Customers who want a trusted cert have two options:

- Bring a domain + ACM cert and use T2 (which fronts the EC2 with an ALB).
- Replace `/opt/cast-clone/certs/server.{crt,key}` on disk with their own cert, then `docker restart cast-clone-caddy-1`.

## Inputs (selected)

| Name | Default | Notes |
|---|---|---|
| `instance_type` | `m6i.xlarge` | Must be Nitro-class (m5+, c5+, r5+, t3+) for the data-volume detection logic |
| `data_volume_size_gb` | `100` | Sizing presets: 50 / 100 / 250 / 1000 by LOC ceiling |
| `image_registry` | required | e.g. `<acct>.dkr.ecr.us-east-1.amazonaws.com/cast-clone` |
| `image_tag` | `latest` | Applied to backend, frontend, mcp |
| `allow_https_from_cidrs` | `["0.0.0.0/0"]` | Tighten for private deployments |
| `allow_ssh_from_cidrs` | `[]` | Empty = SSM-only access (recommended) |
| `allocate_eip` | `true` | Required for stable URL across stop/start |
| `ai_provider` | `bedrock` | `bedrock` / `anthropic` / `openai` |

Full input list: `variables.tf`.

## Outputs

`instance_id`, `private_ip`, `public_ip`, `public_dns`, `security_group_id`, `data_volume_id`, `application_url`.

## Operational notes

- `lifecycle { ignore_changes = [user_data] }` is set on the instance: changes to user-data templates do **not** automatically replace the instance (which would lose the root volume's container layers). To force a re-bootstrap, taint the instance: `terraform taint module.monolith.aws_instance.this`. The data volume is preserved across instance replacement.
- Both root and data volumes are encrypted at rest with the default AWS-managed key.
- IMDSv2 is required (`http_tokens = "required"`).
