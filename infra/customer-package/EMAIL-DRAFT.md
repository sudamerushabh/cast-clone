# Email draft — ChangeSafe self-service deployment

## Subject

Deploying ChangeSafe in your AWS account — package + next step

---

## Body (paste into your email client)

Hi [Customer Name],

Attached is everything you need to deploy ChangeSafe into your own AWS account: a Terraform package (`changesafe-deployment.zip`, ~40 KB) and a step-by-step guide. Your AWS account is never accessed by us — you run `terraform apply` from your own laptop, and the application pulls container images directly from our ECR registry.

**What gets deployed**

AWS resources (in your account):

- VPC + 2-AZ public/private subnets, route tables, Internet Gateway
- 1× EC2 instance (m6i.xlarge default — sized for up to 1M LOC)
- 100 GB EBS gp3 data volume + 30 GB root volume (both encrypted)
- 1× Elastic IP, 1× security group (HTTPS 443 in, all out)
- AWS Secrets Manager — 2 secrets (Postgres, Neo4j passwords)
- IAM role + instance profile (Bedrock invoke + Secrets read + ECR pull + SSM)
- AWS Backup — daily EBS snapshots, 7-day retention
- AWS Bedrock — invoke permission scoped to Anthropic models (token usage on your bill)

Application stack (8 Docker containers running on the EC2 via Compose):

- **changesafe-backend** — FastAPI + SCIP indexers (Java, TypeScript, Python, .NET) + Tree-sitter + sqlglot
- **changesafe-frontend** — Next.js 16 UI with Cytoscape graph viz + Monaco code viewer
- **changesafe-mcp** — Model Context Protocol server for AI agent integration
- **caddy** — TLS reverse proxy on 443 (self-signed cert auto-generated at first boot)
- **postgres 16** — relational database
- **neo4j 5 Community** — code graph database (with APOC + Graph Data Science plugins)
- **redis 7** — cache + pub/sub for live progress streaming
- **minio** — S3-compatible object store for uploaded source archives

All data stays in your AWS account. The only outbound traffic is intra-AWS Bedrock calls and the one-time ECR image pull on first boot.

**One thing we need from you**

Please reply with your **12-digit AWS account ID**:

```
aws sts get-caller-identity --query Account --output text
```

Once we have it, we grant your account read-only access to our ECR registry (5 minutes on our side). We confirm by reply, and you're ready to deploy.

**What happens after that**

1. Unzip the package, edit `terraform.tfvars` (region, instance size, allowed source CIDR).
2. Run `terraform init` and `terraform apply` (~3 minutes).
3. Wait ~5 minutes for the EC2 first-boot bootstrap (Docker + image pull + 8-container compose-up).
4. Open the `application_url` output in your browser, navigate to `/setup`, create your first admin account.

**Prerequisites on your side**

- AWS account with admin access
- Terraform ≥ 1.9
- AWS CLI v2 configured
- Bedrock model access enabled for Anthropic Claude (one-time, takes 30 seconds in the AWS console)

**Cost**

~$140/month for the default m6i.xlarge size in us-east-1 (covers up to 1M LOC). Bedrock token usage is metered separately on your AWS bill. Sizing matrix for larger codebases is in the attached guide.

**Licensing**

The deployment starts in UNLICENSED state. After your first admin login, navigate to **Settings → License**, copy your **Installation ID**, and reply with it to request a license JWT (we typically turn this around within one business day). To activate, drag-and-drop the `.jwt` file we email you onto the Settings → License upload area — the app verifies, persists to disk, and reloads state without a restart.

**Support**

If anything fails, the deployment guide includes a troubleshooting section listing exactly which logs to send. Most issues are (a) Bedrock model access not granted in your region or (b) `allow_https_from_cidrs` too tight. Both fix in minutes.

Looking forward to getting you live.

Best,
Rushabh Sudame

---

## Pre-send checklist

- [ ] Replace `[Customer Name]` with the recipient's name.
- [ ] Verify `changesafe-deployment.zip` (renamed from cast-clone-deployment.zip) is attached.
- [ ] Image tag in the zip's `terraform.tfvars.example` matches what your ECR currently has tagged as `latest` (currently `v0.0.4-frontfix`).
- [ ] Subject line set.

---

## After they reply with their AWS account ID

Run this on your laptop with admin AWS creds for account 317440775524 — replace `CUSTOMER_ACCOUNT_ID`:

```bash
CUSTOMER_ACCOUNT_ID=123456789012   # ← replace with theirs

POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "AllowCustomerCrossAccountPull",
    "Effect": "Allow",
    "Principal": { "AWS": "arn:aws:iam::${CUSTOMER_ACCOUNT_ID}:root" },
    "Action": [
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
      "ecr:BatchCheckLayerAvailability",
      "ecr:DescribeImages",
      "ecr:DescribeRepositories",
      "ecr:ListImages"
    ]
  }]
}
EOF
)

for REPO in cast-clone/cast-clone-backend cast-clone/cast-clone-frontend cast-clone/cast-clone-mcp; do
  aws ecr set-repository-policy \
    --repository-name "$REPO" \
    --policy-text "$POLICY" \
    --region us-east-1
done
```

Then send a one-line follow-up:

> ECR access granted for AWS account `${CUSTOMER_ACCOUNT_ID}` on the three ChangeSafe image repositories in us-east-1. You're cleared to deploy whenever you're ready — just `terraform apply` per the guide. Ping me when done or if you hit anything.
