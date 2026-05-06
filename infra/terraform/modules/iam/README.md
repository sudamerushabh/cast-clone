# Module: `cast-clone-iam`

IAM roles and policies for the cast-clone runtime. Creates one **application role** (used at runtime by app code) and optionally an **ECS task-execution role** (used by ECS itself for image pulls / log writes / secret injection at task start).

## What gets created when

| Tier | Flags to set | Resources created |
|---|---|---|
| T1 — single EC2 | `create_ec2_instance_profile = true` | application role + EC2 instance profile |
| T2 / T3 — Fargate | `create_ecs_task_role = true`, `create_ecs_execution_role = true` | application role + ECS task-execution role |

The application role is always created. The flags control which trust principals can assume it and which adapter resources (instance profile vs. execution role) get provisioned alongside.

## Application role permissions

Always attached:

| Policy | Permits |
|---|---|
| `bedrock-invoke` | `bedrock:InvokeModel*` on `bedrock_model_arns` (default: all Anthropic foundation models in any region) |
| `cloudwatch-logs` | `logs:Create*` / `logs:PutLogEvents` scoped to log groups under `log_group_prefix` (default `/cast-clone`) |

Conditionally attached:

| Policy | Trigger | Permits |
|---|---|---|
| `secrets-read` | `secret_arns` non-empty | `secretsmanager:GetSecretValue` + `DescribeSecret` on those ARNs only |
| `s3-archives` | `s3_bucket_arns` non-empty | `s3:Get/Put/DeleteObject` on `${arn}/*` and `s3:ListBucket` on the bucket itself |

## Why two ECS roles?

ECS Fargate uses two separate role concepts and people frequently conflate them:

| Role | Assumed by | Purpose |
|---|---|---|
| **Task role** (= our application role with `create_ecs_task_role = true`) | the running container at runtime | What the app code can do (Bedrock, S3, Secrets) |
| **Execution role** (`create_ecs_execution_role = true`) | the ECS agent at task start | Image pulls from ECR, log group writes, fetching secrets to inject as env vars |

Splitting them is AWS best practice: the execution role only has permissions to start the task, the task role only has permissions to do the work. Compromise of one doesn't grant the other.

## Bedrock ARN scoping

Default `bedrock_model_arns = ["arn:aws:bedrock:*::foundation-model/anthropic.*"]` allows any Anthropic model in any region. For a tighter policy (e.g., only Claude Sonnet 4.6 cross-region inference profiles in `us-east-1`):

```hcl
bedrock_model_arns = [
  "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-6-20251022-v1:0",
  "arn:aws:bedrock:us-east-1:*:inference-profile/us.anthropic.claude-sonnet-4-6-*",
]
```

## Inputs

| Name | Type | Default |
|---|---|---|
| `name_prefix` | string | — |
| `create_ec2_instance_profile` | bool | `false` |
| `create_ecs_task_role` | bool | `false` |
| `create_ecs_execution_role` | bool | `false` |
| `bedrock_model_arns` | list(string) | all Anthropic models |
| `secret_arns` | list(string) | `[]` |
| `s3_bucket_arns` | list(string) | `[]` |
| `log_group_prefix` | string | `/cast-clone` |
| `tags` | map(string) | `{}` |

## Outputs

`application_role_arn`, `application_role_name`, `ec2_instance_profile_name`, `ec2_instance_profile_arn`, `ecs_execution_role_arn`.

## Example (T1)

```hcl
module "iam" {
  source                      = "../../modules/iam"
  name_prefix                 = "castclone-t1"
  create_ec2_instance_profile = true
  secret_arns                 = module.secrets.all_secret_arns
  tags                        = { Project = "cast-clone", Tier = "t1" }
}

resource "aws_instance" "monolith" {
  iam_instance_profile = module.iam.ec2_instance_profile_name
  # ...
}
```

## Example (T2)

```hcl
module "iam" {
  source                    = "../../modules/iam"
  name_prefix               = "castclone-t2"
  create_ecs_task_role      = true
  create_ecs_execution_role = true
  secret_arns               = module.secrets.all_secret_arns
  s3_bucket_arns            = [module.s3_archives.bucket_arn]
  tags                      = { Project = "cast-clone", Tier = "t2" }
}

resource "aws_ecs_task_definition" "backend" {
  task_role_arn      = module.iam.application_role_arn
  execution_role_arn = module.iam.ecs_execution_role_arn
  # ...
}
```
