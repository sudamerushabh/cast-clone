# Module: `cast-clone-secrets`

Provisions AWS Secrets Manager entries for the cast-clone runtime: database passwords, license JWT, and optional AI provider keys.

## Secrets created

| Path | Source | Always created? |
|---|---|---|
| `<name_prefix>/postgres/password` | random 32-char (or `pg_password_override`) | yes |
| `<name_prefix>/neo4j/password` | random 32-char (or `neo4j_password_override`) | yes |
| `<name_prefix>/license/jwt` | `license_jwt` var (defaults to `TRIAL_PLACEHOLDER`) | yes |
| `<name_prefix>/ai/anthropic-api-key` | `anthropic_api_key` var | only if set |
| `<name_prefix>/ai/openai-api-key` | `openai_api_key` var | only if set |

## License JWT semantics

| `license_jwt` value | Stored secret value | App behavior |
|---|---|---|
| `null` (default) | `TRIAL_PLACEHOLDER` | Treats stack as trial; reads pre-baked AMI trial JWT and starts the 14-day clock at first boot |
| `"<jwt>"` | the JWT verbatim | Validates offline against embedded public key; honors expiry / tier / LOC limits |

A customer who buys a license post-trial updates the secret value via the AWS Console, CLI, or Terraform — no redeploy required (app re-reads the secret on each task start in T2/T3, or on `systemctl restart cast-clone` in T1).

## Password character set

Generated passwords use letters, digits, and the conservative special set `-_=+!#%*` (62 alphanumerics + 8 specials → ~196 bits of entropy in 32 chars). The set deliberately excludes:

| Excluded | Reason |
|---|---|
| `$` | docker-compose `.env` files interpret `$` as variable substitution |
| `<` `>` `(` `)` `{` `}` | Shell metacharacters in unquoted contexts |
| `:` `/` `@` `?` `&` | URI-component delimiters in connection strings |
| `[` `]` | Some shells perform glob expansion |

## Inputs

| Name | Type | Default | Sensitive |
|---|---|---|---|
| `name_prefix` | string | — | no |
| `kms_key_id` | string | `null` (uses AWS-managed key) | no |
| `recovery_window_in_days` | number | `7` | no |
| `generate_pg_password` | bool | `true` | no |
| `pg_password_override` | string | `null` | yes |
| `generate_neo4j_password` | bool | `true` | no |
| `neo4j_password_override` | string | `null` | yes |
| `license_jwt` | string | `null` | yes |
| `anthropic_api_key` | string | `null` | yes |
| `openai_api_key` | string | `null` | yes |
| `tags` | map(string) | `{}` | no |

## Outputs

`pg_password_secret_arn`, `neo4j_password_secret_arn`, `license_jwt_secret_arn`, `anthropic_api_key_secret_arn`, `openai_api_key_secret_arn`, `all_secret_arns`.

## Example

```hcl
module "secrets" {
  source      = "../../modules/secrets"
  name_prefix = "castclone-prod"
  tags        = { Project = "cast-clone", Environment = "prod" }
}

# wired into iam module
module "iam" {
  source      = "../../modules/iam"
  name_prefix = "castclone-prod"
  secret_arns = module.secrets.all_secret_arns
  ...
}
```
