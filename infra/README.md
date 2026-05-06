# CAST-Clone Infrastructure

Terraform, Packer, and CloudFormation artifacts for deploying CAST-Clone into a customer's AWS account.

## Layout

| Path | Purpose |
|---|---|
| `terraform/modules/` | Reusable Terraform modules (network, secrets, iam, ...) |
| `terraform/tiers/` | Root modules per deployment tier (T1 starter, T2 standard, T3 enterprise) |
| `terraform/examples/` | Sample `*.tfvars.example` files for common shapes |
| `marketplace/packer/` | Packer templates for the T1 AMI |
| `marketplace/cloudformation/` | CFN templates referenced by Marketplace listings |
| `scripts/` | One-off helpers (image publish, license signing, release) |

See `cast-clone-backend/docs/10-DEPLOYMENT.md` for product-level deployment context.

## Tier matrix

| Tier | Topology | Marketplace vehicle |
|---|---|---|
| T1 — Starter | Single EC2 + Docker Compose + EBS | AMI Quick Launch |
| T2 — Standard | ECS Fargate + RDS + ElastiCache + S3 + Neo4j EC2 | CloudFormation product |
| T3 — Enterprise | T2 Multi-AZ + cross-region backups; Neo4j single-AZ with backup-based recovery | CloudFormation product |

## Conventions

- Terraform `>= 1.9.0`, AWS provider `~> 5.70`.
- All resources tagged `Project=cast-clone`, `ManagedBy=terraform`, `Tier=<tier>`, `Environment=<env>`.
- Module names: `cast-clone-<resource>`.
- State backend: not configured by default. Enable an S3 backend in your tier root before running in shared environments.
- Image distribution: ECR Private (your account) for direct sales; AWS Marketplace ECR for Marketplace installs. Same Dockerfiles, dual-push from CI.
- Neo4j: Community edition everywhere; T3 HA is application-tier only (Neo4j is recoverable single-AZ).
- Licensing: out-of-band email-issued JWT, validated offline by the application.

## Regions

Marketplace listing replicates to: `us-east-1`, `us-east-2`, `us-west-2`, `eu-west-1`, `eu-central-1`, `ap-south-1`, `ap-south-2`, `ap-southeast-1`, `ap-southeast-2`, `ap-northeast-1`.

## Build order

1. `terraform/modules/{network,secrets,iam}` ← step 1 (this commit)
2. `terraform/tiers/tier1-starter` end-to-end
3. `marketplace/packer/tier1-monolith.pkr.hcl` + `marketplace/cloudformation/tier1-quicklaunch.yaml`
4. T2 modules (`postgres_rds`, `redis_elasticache`, `s3_archives`, `ecs_*`, `alb`, `neo4j_ec2_single`)
5. `terraform/tiers/tier2-standard` + Marketplace CFN listing
6. T3 modules + `terraform/tiers/tier3-enterprise` + Marketplace CFN listing
