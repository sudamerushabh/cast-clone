# Terraform

Reusable modules and tier root modules for cast-clone deployments.

## Module catalog

| Module | Status | Used by |
|---|---|---|
| `modules/network` | Step 1 | T1, T2, T3 |
| `modules/secrets` | Step 1 | T1, T2, T3 |
| `modules/iam` | Step 1 | T1, T2, T3 |
| `modules/monolith_ec2` | Pending | T1 |
| `modules/neo4j_ec2_single` | Pending | T2, T3 |
| `modules/postgres_rds` | Pending | T2, T3 |
| `modules/redis_elasticache` | Pending | T2, T3 |
| `modules/s3_archives` | Pending | T2, T3 |
| `modules/ecs_cluster` | Pending | T2, T3 |
| `modules/ecs_service` | Pending | T2, T3 |
| `modules/alb` | Pending | T2, T3 |
| `modules/backups` | Pending | T1, T2, T3 |

## Module conventions

- Each module has `main.tf`, `variables.tf`, `outputs.tf`, `versions.tf`, `README.md`.
- No `provider` blocks inside modules. Tier roots configure providers.
- All inputs validated where the constraint is non-obvious (CIDRs, AZ counts, retention windows).
- Default `tags` variable merged into every taggable resource.
- Sensitive variables marked `sensitive = true`; sensitive outputs likewise.

## Running a module standalone

Modules are not designed to be `terraform apply`-ed in isolation — call them from a tier root or a throwaway test root:

```hcl
module "network" {
  source = "../../modules/network"

  name_prefix = "castclone-dev"
  tags = {
    Project     = "cast-clone"
    ManagedBy   = "terraform"
    Environment = "dev"
  }
}
```
