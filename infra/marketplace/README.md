# Marketplace Artifacts

Everything needed to publish cast-clone as an AWS Marketplace product.

## Layout

| Path | Purpose |
|---|---|
| `packer/` | Packer template that builds the T1 monolith AMI (one per release version) |
| `cloudformation/` | CFN templates referenced by Marketplace listings |
| `listing/` | Listing copy + pricing notes + support runbook (filled in pre-submission) |

## Listing types we will publish

| Tier | Marketplace product type | Customer flow |
|---|---|---|
| **T1 — Starter** | **AMI with CloudFormation** | Customer clicks "Launch in your AWS account" → fills 4 params → CFN stack deploys VPC + EC2 + EBS + Secrets + IAM + Backups |
| **T2 — Standard** (later) | **Container product (CFN-delivered)** | Same flow; CFN deploys ECS + RDS + ElastiCache + S3 + Neo4j EC2 |
| **T3 — Enterprise** (later) | Same listing as T2, second deployment option | Same flow with multi-AZ + larger sizing |

T2/T3 ship later — see `infra/terraform/README.md` build order.

## Publishing flow (T1)

```
1. Build images
   infra/scripts/publish-images.sh
     → builds backend/frontend/mcp from cast-clone-backend/ and cast-clone-frontend/
     → pushes to <your-acct>.dkr.ecr.us-east-1.amazonaws.com/cast-clone

2. Sign a trial JWT (long backstop, 365 days)
   infra/scripts/sign-trial-license.sh > /tmp/trial.jwt

3. Build the AMI for every region
   cd infra/marketplace/packer
   packer build \
     -var "image_registry=<your-acct>.dkr.ecr.us-east-1.amazonaws.com/cast-clone" \
     -var "image_tag=v0.1.0" \
     -var "version=v0.1.0" \
     -var "trial_license_jwt=$(cat /tmp/trial.jwt)" \
     tier1-monolith.pkr.hcl
   # Outputs manifest.json with one AMI ID per region.

4. Update the CFN template with the new AMI IDs
   infra/scripts/update-cfn-mappings.sh manifest.json infra/marketplace/cloudformation/tier1-quicklaunch.yaml

5. Submit to AWS Marketplace
   - In Marketplace Management Portal, create new version of listing.
   - Upload tier1-quicklaunch.yaml.
   - Reference the AMI IDs from manifest.json.
   - Marketplace runs an automated AMI scan + manual review (~5 business days).
```

## Trial license behavior

A 14-day trial JWT is baked into every AMI at `/etc/cast-clone/trial-license.jwt`. Two important semantics:

- **The JWT's `exp` is 365 days from sign time**, not 14 — otherwise customers launching the AMI months after publish would receive an already-expired trial.
- **The actual 14-day clock** is enforced by the application using `first_boot_at` (recorded to `/var/lib/cast-clone/license-state.json` on first boot of the customer's instance). Effective expiry = `min(jwt.exp, first_boot_at + 14 days)`.
- **Customers buy** by emailing you. You sign a production JWT via `license-infra/` (the existing CDK app) and email it back. Customer pastes into AWS Secrets Manager → app picks it up on next backend container restart.

## Image distribution model

| Path | What customer sees |
|---|---|
| **Marketplace AMI** (this directory) | Images pre-baked into AMI. Customer never authenticates to any registry. |
| **Direct Terraform apply** (`infra/terraform/tiers/tier1-starter`) | Images pulled from your private ECR at first boot. Customer's account ID must be granted ECR pull permission. |

Same Dockerfiles, two distribution channels — `infra/scripts/publish-images.sh` pushes to your private ECR; Marketplace AMI bake pulls from there into the AMI.
