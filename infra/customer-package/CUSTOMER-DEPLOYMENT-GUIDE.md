# Cast-Clone — Self-Service Deployment Guide

Deploy Cast-Clone (architecture intelligence platform) into your own AWS account using Terraform. The application runs as a fully self-contained Docker stack on a single EC2 instance. No data leaves your AWS account; we only publish container images.

---

## What gets deployed

A single CloudFormation-equivalent Terraform stack that creates:

| Resource | Purpose |
|---|---|
| VPC + 2-AZ public/private subnets | Network isolation |
| 1× EC2 instance (`m6i.xlarge` default, configurable) | Application host |
| EBS data volume (100 GB gp3 default) | Postgres + Neo4j + uploaded archives |
| Elastic IP | Stable public address |
| Security group | HTTPS (443) inbound only |
| 3× Secrets Manager secrets | Postgres password, Neo4j password, license JWT |
| IAM role + instance profile | Bedrock invoke + Secrets read + ECR pull + SSM access |
| AWS Backup vault + plan | Daily EBS snapshots, 7-day retention (configurable) |

Inside the EC2 instance, Docker Compose runs **8 containers**: Postgres 16, Neo4j 5 Community (with APOC + Graph Data Science), Redis 7, MinIO, Cast-Clone backend (FastAPI + SCIP indexers for Java/TypeScript/Python/.NET), Cast-Clone frontend (Next.js), Cast-Clone MCP server, and Caddy (TLS reverse proxy with self-signed cert).

---

## Cost estimate (us-east-1)

| Component | Approx. monthly cost |
|---|---|
| EC2 m6i.xlarge | ~$120 |
| EBS gp3 (100 GB + 30 GB root) | ~$13 |
| Elastic IP (when attached) | $0 |
| Secrets Manager (3 secrets) | ~$1.20 |
| AWS Backup (snapshots) | ~$3–5 |
| Bedrock model invocations | Pay-per-token (varies by usage) |
| **Total infrastructure** | **~$140–150/mo** |

For 100k–1M LOC codebases, this is the right size. For 5M+ LOC scale up `instance_type` to `m6i.2xlarge` and `data_volume_size_gb` to 250–500 GB.

---

## Prerequisites

1. **AWS account** with administrator (or equivalent) IAM access.
2. **Terraform ≥ 1.9.0** (`brew install terraform` on macOS, see https://developer.hashicorp.com/terraform/install).
3. **AWS CLI v2** configured (`aws configure`).
4. **Bedrock foundation model access enabled** in your deployment region — one-time per AWS account, takes 30 seconds at https://console.aws.amazon.com/bedrock/home → Model access → request access to "Anthropic Claude" models.
5. **Your AWS account ID** — share this with us so we can grant your account read access to our private ECR (one-time setup).

---

## Step-by-step deployment

### 1. Send us your AWS account ID

Reply to this email with your 12-digit AWS account ID. We will grant your account read access to our ECR registry holding the Cast-Clone images and confirm with you that it's done.

You can find your account ID with:

```bash
aws sts get-caller-identity --query Account --output text
```

### 2. Unzip the deployment package

The attached `cast-clone-deployment.zip` contains the Terraform modules and tier-1 root module. Unzip into any directory:

```bash
unzip cast-clone-deployment.zip -d cast-clone-deployment
cd cast-clone-deployment
```

Directory layout:

```
cast-clone-deployment/
├── modules/
│   ├── network/          VPC + subnets + NAT (optional)
│   ├── secrets/          Secrets Manager entries
│   ├── iam/              IAM role + instance profile
│   └── monolith_ec2/     EC2 + EBS + cert generation + bootstrap
├── tiers/
│   └── tier1-starter/    Root module — call this with terraform apply
├── README.md             Same as this file
└── CUSTOMER-DEPLOYMENT-GUIDE.md   (this document)
```

### 3. Configure your tfvars

```bash
cd tiers/tier1-starter
cp terraform.tfvars.example terraform.tfvars
```

Open `terraform.tfvars` and review the values. The most important ones:

| Variable | Default | Notes |
|---|---|---|
| `aws_region` | `us-east-1` | Pick the region closest to your team |
| `instance_type` | `m6i.xlarge` | See sizing matrix below |
| `data_volume_size_gb` | `100` | Increase for >1M LOC codebases |
| `image_tag` | (we will tell you) | Pin to the version we ship |
| `allow_https_from_cidrs` | `["0.0.0.0/0"]` | **Tighten this to your corporate CIDR** for private deploys |

The `image_registry` value is pre-filled with our ECR path. **Do not change it** unless we tell you otherwise.

### 4. Run Terraform

```bash
terraform init
terraform plan
terraform apply
```

`apply` takes ~3 minutes for the AWS resources, then **wait an additional ~5 minutes** for the EC2 instance's first-boot bootstrap (Docker install, ECR image pull of ~3.4 GB backend image, 8-container compose-up, Postgres + Neo4j healthchecks).

### 5. Open the application

Terraform output `application_url` gives the HTTPS endpoint:

```bash
terraform output application_url
# → https://<your-elastic-ip>
```

The certificate is self-signed; your browser will warn on first visit. Accept the warning. You'll land on a setup page where you create the first admin account (username + email + password of your choice).

### 6. Activate your license (post-trial)

The instance starts in **UNLICENSED / trial** state. Open the application, go to **Settings → License**, and you'll see your **Installation ID** — share that with us when requesting a license.

After purchase we'll email you a production JWT (a single `.jwt` file). To install it:

1. Open `https://<your-elastic-ip>/settings/license` in your browser.
2. Drag-and-drop the `.jwt` file into the **Choose a license file** area (or click to browse). The app verifies the signature against the embedded public key, atomically replaces the license file on the persistent volume, and reloads state — no restart needed.
3. The license status flips to **LICENSED_HEALTHY**, your tier and LOC limit appear, and the global "No license installed" banner disappears.

The license file is stored at `/var/lib/cast-clone/license/license.jwt` on the host (bind-mounted into the backend container as `/var/lib/changesafe/license/license.jwt`). It survives container restarts, image upgrades, and `docker compose down/up`.

**Advanced — pre-seed via Terraform**: if you'd rather have the license already in place before the customer-facing UI is available, set `license_jwt = "..."` in `terraform.tfvars` before `terraform apply`. The bootstrap script will write the file to the persistent volume on first boot.

---

## Operational tasks

### Tightening network access

Edit `terraform.tfvars`:

```hcl
allow_https_from_cidrs = ["10.0.0.0/8", "192.168.1.0/24"]
```

Then `terraform apply`. Updates the security group in seconds; no instance restart needed.

### SSH-free shell access

Use AWS Systems Manager Session Manager — no SSH key required:

```bash
INSTANCE_ID=$(terraform output -raw instance_id)
aws ssm start-session --target "$INSTANCE_ID"
```

### Tailing the application logs

```bash
# Inside an SSM session:
sudo docker compose -f /opt/cast-clone/docker-compose.yml logs -f backend
sudo docker compose -f /opt/cast-clone/docker-compose.yml logs -f frontend
```

### Restoring from a backup

```bash
# List recovery points:
aws backup list-recovery-points-by-backup-vault \
  --backup-vault-name "$(terraform output -raw backup_vault_arn | sed 's|.*/||')"

# Restore creates a new EBS volume; detach the live one, attach the restored one
# at /dev/sdf, reboot the instance.
```

### Tearing down

```bash
terraform destroy
# Note: AWS Secrets Manager has a 7-day soft-delete recovery window. If you re-deploy
# within 7 days using the same name_prefix, force-delete the pending secrets first:
for SECRET in postgres/password neo4j/password license/jwt; do
  aws secretsmanager delete-secret \
    --secret-id "<your-name_prefix>/$SECRET" \
    --force-delete-without-recovery
done
```

---

## Sizing matrix

| Codebase size | `instance_type` | `data_volume_size_gb` | Approx. cost/mo (us-east-1) |
|---|---|---|---|
| Up to 100k LOC | `m6i.large` | 50 | ~$80 |
| Up to 1M LOC | `m6i.xlarge` (default) | 100 | ~$140 |
| Up to 5M LOC | `m6i.2xlarge` | 250 | ~$280 |
| Up to 10M LOC | `r6i.4xlarge` | 1000 | ~$900 |

---

## Security notes

- **All data stays in your AWS account**: source archives uploaded to MinIO are written only to the EBS volume; Postgres + Neo4j are likewise local.
- **TLS in transit**: Caddy serves HTTPS (self-signed by default; supply your own ACM cert by editing the security group + adding a Route53 record + ACM certificate in a follow-up Terraform stack).
- **Secrets at rest**: Postgres + Neo4j passwords are AWS Secrets Manager (encrypted by `aws/secretsmanager` KMS key); license JWT likewise.
- **AI provider — Bedrock authentication via the EC2 instance role.** The default is AWS Bedrock (Anthropic Claude). The instance role granted by Terraform carries `bedrock:InvokeModel*` scoped to Anthropic foundation models only. The backend container picks up role credentials from EC2 Instance Metadata Service (IMDSv2 enforced; hop limit 2 set so Docker bridge traffic can reach IMDS) and uses them transparently — no static AWS keys are stored in the container, in environment variables, or in Secrets Manager. Bedrock requests stay inside AWS; token usage bills your account's Bedrock meter. To use Anthropic API or OpenAI directly instead, set `ai_provider = "anthropic"` (or `"openai"`) in tfvars and provide the API key.
- **Image scanning**: each container image is scanned by AWS ECR on push. We will share scan reports on request.

---

## Support

If `terraform apply` fails or the application doesn't come up after 8 minutes, please send us:

1. The output of `terraform output` (especially `instance_id` and `public_ip`).
2. The bootstrap log: SSM into the instance and run:
   ```bash
   sudo tail -200 /var/log/cast-clone-bootstrap.log
   sudo docker compose -f /opt/cast-clone/docker-compose.yml ps
   ```
3. The output of `aws sts get-caller-identity` (so we can confirm ECR cross-account grant covers your account).

We will respond within one business day.
