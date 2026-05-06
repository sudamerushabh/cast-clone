# Tier 1 — Starter

The smallest deployable cast-clone install: one EC2 instance running everything via Docker Compose, one EBS data volume, one Elastic IP, daily AWS Backup snapshots. ~$200–400/month depending on instance size and data-volume size.

This tier is the basis for the **Marketplace AMI Quick Launch** product (step 3) — the same module backs both `terraform apply` (this directory) and the Packer-built AMI.

## What gets created

```
VPC (10.42.0.0/16)
├── public subnet (AZ-A)
│   └── EC2 m6i.xlarge
│       ├── EIP
│       ├── Security group (443 + optional 22)
│       ├── Root EBS (30 GB gp3, encrypted)
│       └── Data EBS (100 GB gp3, encrypted) → /var/lib/cast-clone
└── (no NAT, no private subnets)

AWS Secrets Manager
├── castclone-t1/postgres/password   (random 32 chars)
├── castclone-t1/neo4j/password      (random 32 chars)
└── castclone-t1/license/jwt         (TRIAL_PLACEHOLDER until customer pastes real JWT)

IAM
├── castclone-t1-application         (role assumed by EC2)
│   ├── bedrock:InvokeModel*  (Anthropic models)
│   ├── secretsmanager:GetSecretValue  (3 ARNs above)
│   └── logs:Put*  (/cast-clone/*)
├── castclone-t1-application         (instance profile wrapping the role)
└── castclone-t1-backup-role         (used by AWS Backup)

AWS Backup
├── castclone-t1-vault
├── castclone-t1-daily plan          (cron: 05:00 UTC, 7-day retention)
└── castclone-t1-tagged selection    (resources tagged CastCloneBackup=true)
```

## Sizing matrix

| LOC ceiling | `instance_type` | `data_volume_size_gb` | Approx. monthly cost (us-east-1) |
|---|---|---|---|
| 100k | `m6i.large` | 50 | ~$80 |
| 1M | `m6i.xlarge` (default) | 100 | ~$180 |
| 5M | `m6i.2xlarge` | 250 | ~$340 |
| 10M | `r6i.4xlarge` | 1000 | ~$900 (consider T2 instead) |

Excludes data-transfer, EIP, and AWS Backup snapshot storage.

## Prerequisites

1. AWS account with admin or equivalent IAM permissions for the user running Terraform.
2. **Bedrock model access** enabled in the deployment region for the Anthropic models you intend to use. This is a one-time per-account action via the Bedrock console.
3. Container images published to an accessible registry. For pre-Marketplace testing in your own AWS account, push to your private ECR and grant the EC2 instance role cross-account pull permissions, OR temporarily make the images public.
4. Terraform `>= 1.9.0`.

## Quick start

```bash
cd infra/terraform/tiers/tier1-starter
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars: set image_registry + image_tag at minimum.

terraform init
terraform plan
terraform apply
```

Apply takes ~3–4 minutes. Cloud-init bootstrap (Docker install + image pull + container start) takes another ~5 minutes after the instance shows `running`. Watch progress:

```bash
INSTANCE_ID=$(terraform output -raw instance_id)
aws ssm start-session --target "$INSTANCE_ID"
# inside the session:
sudo tail -f /var/log/cast-clone-bootstrap.log
sudo docker compose -f /opt/cast-clone/docker-compose.yml ps
```

When all services are healthy, hit the `application_url` output (expect a self-signed cert warning).

## Operational tasks

### Activating a paid license

```bash
aws secretsmanager put-secret-value \
  --secret-id "$(terraform output -raw license_secret_arn)" \
  --secret-string "<paste-the-JWT-here>"

# Restart the backend container so it re-reads the secret.
INSTANCE_ID=$(terraform output -raw instance_id)
aws ssm start-session --target "$INSTANCE_ID" \
  --document-name AWS-StartInteractiveCommand \
  --parameters 'command=["sudo docker restart cast-clone-backend-1"]'
```

### Restoring from a backup

```bash
# Find the recovery point.
aws backup list-recovery-points-by-backup-vault \
  --backup-vault-name "$(terraform output -raw backup_vault_arn | sed 's|.*/||')"

# Restore creates a new EBS volume. Detach the live data volume, attach the
# restored one at /dev/sdf, reboot the instance.
```

### Tightening network access

```hcl
# In terraform.tfvars
allow_https_from_cidrs = ["10.0.0.0/8", "192.168.1.0/24"]
```

`terraform apply` updates the security group in seconds; no instance restart needed.

## Known limitations

- **Self-signed TLS.** Browsers warn on first visit. Acceptable for T1; T2 fronts with an ALB + ACM cert if a domain is provided.
- **No HA.** Single AZ, single instance. Snapshot-based recovery only (~daily granularity).
- **No managed databases.** Postgres + Neo4j run in containers on the same host, sharing one EBS volume. Disk failure = data loss until restore.
- **Trial 14-day clock.** Starts at first boot of the instance, not at AMI launch. Recreating the instance recreates the data volume's `license-state.json` only if the data volume is also recreated (it is not, by default).

For higher availability or larger codebases, see Tier 2 / Tier 3 (pending).
