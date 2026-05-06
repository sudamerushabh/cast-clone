# Packer — T1 Marketplace AMI

Builds a single AMI per release containing Amazon Linux 2023 + Docker + pre-pulled cast-clone images + a baked trial JWT. The AMI replicates to all 10 Marketplace regions in one Packer run.

## Layout

```
packer/
├── tier1-monolith.pkr.hcl    Packer template (source + build blocks)
├── files/
│   ├── bootstrap.sh          Runtime first-boot script (lives at /opt/cast-clone/bootstrap.sh)
│   └── Caddyfile             Reverse-proxy config (TLS termination + path routing)
├── templates/
│   └── docker-compose.yml.tftpl   Rendered at Packer build with image refs frozen
└── scripts/
    ├── install-deps.sh       Docker + compose plugin + jq install
    └── pull-images.sh        ECR login + docker pull of every image needed at runtime
```

## How the AMI runs at customer launch

```
CloudFormation user-data (per stack)
  ↓ exports REGION, *_SECRET_ARN, AI_PROVIDER, BEDROCK_REGION
  ↓ calls /opt/cast-clone/bootstrap.sh

bootstrap.sh
  ├── Locates + formats + mounts EBS data volume → /var/lib/cast-clone
  ├── Generates self-signed TLS cert at /opt/cast-clone/certs/
  ├── aws secretsmanager get-secret-value × 5 (PG, Neo4j, license, optional Anthropic/OpenAI keys)
  ├── Falls back to /etc/cast-clone/trial-license.jwt when the license secret is TRIAL_PLACEHOLDER
  ├── Records first_boot_at to /var/lib/cast-clone/license-state.json (the 14-day trial anchor)
  ├── Writes /opt/cast-clone/.env with secret values
  ├── docker compose up -d  (images already in /var/lib/docker — zero pull)
  └── Installs cast-clone.service systemd unit so containers restart on reboot
```

## Build prerequisites

| Requirement | How to satisfy |
|---|---|
| Packer ≥ 1.10 | `brew install packer` |
| AWS credentials with IAM perms to create AMIs + EC2 + ECR pull | `aws configure` or temporary creds |
| Cast-clone images in your ECR | Run `infra/scripts/publish-images.sh VERSION=v0.1.0 ECR_PRIVATE=...` |
| Trial JWT signed by `license-infra/` | Run `infra/scripts/sign-trial-license.sh > /tmp/trial.jwt` |

## Build commands

```bash
cd infra/marketplace/packer

packer init tier1-monolith.pkr.hcl

packer build \
  -var "image_registry=123456789012.dkr.ecr.us-east-1.amazonaws.com/cast-clone" \
  -var "image_tag=v0.1.0" \
  -var "version=v0.1.0" \
  -var "trial_license_jwt=$(cat /tmp/trial.jwt)" \
  tier1-monolith.pkr.hcl
```

Build takes ~15–20 minutes (instance launch + dnf updates + image pulls). Replication across 10 regions runs in parallel and adds ~10 more minutes.

Output: `manifest.json` containing one AMI ID per region. Pass this to `infra/scripts/update-cfn-mappings.sh` to update the CloudFormation template's `RegionToAMI` mapping.

## Local smoke test

To verify a built AMI works end-to-end **before** publishing to Marketplace:

```bash
# 1. Launch an EC2 instance from the new AMI in your test account.
AMI_ID=$(jq -r '.builds[0].artifact_id' manifest.json | sed 's/.*://')
aws ec2 run-instances \
  --image-id "$AMI_ID" \
  --instance-type m6i.xlarge \
  --subnet-id subnet-... \
  --security-group-ids sg-... \
  --iam-instance-profile Name=castclone-test-profile \
  --user-data file://test-user-data.sh \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=CastCloneBackup,Value=true}]'

# 2. Verify bootstrap completes (typically 60–90 seconds).
aws ssm start-session --target i-... # then: sudo tail -f /var/log/cast-clone/bootstrap.log

# 3. Hit https://<public-ip>/ — expect a self-signed cert warning, then the cast-clone UI.
```

`test-user-data.sh` should export the same env vars CloudFormation will export (`REGION`, `*_SECRET_ARN`, etc.) and call `/opt/cast-clone/bootstrap.sh`.

## Security & Marketplace compliance notes

- **IMDSv2 required** — set in `metadata_options` block.
- **ENA + SR-IOV enabled** — set on the source block; Marketplace AMI scan rejects without these.
- **No bash history, no temp files, no dnf cache** — cleaned in the final provisioner step. Keeps the AMI small and removes any artifacts that would fail the Marketplace security scan.
- **No hardcoded credentials in the AMI** — the trial JWT is signed for a generic `installation_id = "marketplace-trial"`; per-customer secrets are created at CloudFormation deploy time.
- **AMI sharing is implicit via Marketplace** — do not add `ami_users` to the Packer source. Marketplace handles cross-account sharing during listing approval.
