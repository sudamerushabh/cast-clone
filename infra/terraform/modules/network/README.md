# Module: `cast-clone-network`

VPC + 2-AZ public/private subnet pair, with NAT gateway optional. Supports two modes:

| Mode | Trigger | Behavior |
|---|---|---|
| Create | `create_vpc = true` (default) | Provisions VPC, IGW, public + private subnets, route tables, NAT gateway(s) |
| Adopt | `create_vpc = false` | Validates the existing `vpc_id` + `*_subnet_ids` exist; passes them through outputs |

## Subnet plan (create mode)

A `/16` VPC is carved into `/20` subnets. With `availability_zone_count = 2` and the default CIDR `10.42.0.0/16`:

| Subnet | CIDR |
|---|---|
| public AZ-0 | `10.42.0.0/20` |
| public AZ-1 | `10.42.16.0/20` |
| private AZ-0 | `10.42.32.0/20` |
| private AZ-1 | `10.42.48.0/20` |

## NAT topology

| Variable combination | Result | Cost / month (us-east-1) |
|---|---|---|
| `enable_nat_gateway = false` | No NAT (T1 with single EC2 in public subnet) | $0 |
| `enable_nat_gateway = true`, `single_nat_gateway = true` (default) | One NAT in AZ-0 serves all private subnets | ~$32 + data |
| `enable_nat_gateway = true`, `single_nat_gateway = false` | One NAT per AZ (HA, T3) | ~$32 × N AZs |

## Inputs

| Name | Type | Default | Required |
|---|---|---|---|
| `name_prefix` | string | — | yes |
| `create_vpc` | bool | `true` | no |
| `vpc_cidr` | string | `10.42.0.0/16` | no |
| `availability_zone_count` | number | `2` | no |
| `enable_nat_gateway` | bool | `true` | no |
| `single_nat_gateway` | bool | `true` | no |
| `vpc_id` | string | `null` | required when `create_vpc = false` |
| `public_subnet_ids` | list(string) | `[]` | required when `create_vpc = false` |
| `private_subnet_ids` | list(string) | `[]` | required when `create_vpc = false` |
| `tags` | map(string) | `{}` | no |

## Outputs

`vpc_id`, `vpc_cidr_block`, `public_subnet_ids`, `private_subnet_ids`, `availability_zones`, `nat_gateway_ids`, `internet_gateway_id`.

## Examples

**T1 starter (create VPC, no NAT — single EC2 lives in a public subnet):**

```hcl
module "network" {
  source             = "../../modules/network"
  name_prefix        = "castclone-t1"
  enable_nat_gateway = false
  tags               = { Project = "cast-clone", Tier = "t1" }
}
```

**T3 enterprise (adopt existing landing-zone VPC):**

```hcl
module "network" {
  source             = "../../modules/network"
  name_prefix        = "castclone-prod"
  create_vpc         = false
  vpc_id             = "vpc-0123456789abcdef0"
  public_subnet_ids  = ["subnet-aaa", "subnet-bbb"]
  private_subnet_ids = ["subnet-ccc", "subnet-ddd"]
  tags               = { Project = "cast-clone", Tier = "t3" }
}
```
