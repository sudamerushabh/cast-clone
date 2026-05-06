# CloudFormation — Marketplace Quick Launch

The CloudFormation template AWS Marketplace deploys when a customer clicks **Launch in your AWS account** on the T1 Starter listing.

## Why CloudFormation, not Terraform

AWS Marketplace's "AMI with CloudFormation" listing type only accepts CFN. Customers never see Terraform — they fill in 4 parameters in the Marketplace launch UI, AWS Marketplace creates a CloudFormation stack on their behalf, and the AMI ID is auto-injected from the listing's region map.

For non-Marketplace direct sales, we use the Terraform tier root at `infra/terraform/tiers/tier1-starter` instead.

## What the stack creates

Mirrors the Terraform T1 starter exactly:

```
VPC (10.42.0.0/16) + IGW + 1 public subnet
Security group (443 ingress, all egress)
3 Secrets Manager secrets (postgres, neo4j, license)
IAM role + instance profile (Bedrock + Secrets Manager + SSM + CloudWatch Logs)
EC2 instance (Marketplace AMI)
EBS data volume + attachment
Elastic IP + association
AWS Backup vault + plan + selection
```

## Customer-facing parameters (intentionally minimal)

| Parameter | Default | Notes |
|---|---|---|
| `InstanceType` | `m6i.xlarge` | 6 sizes from `m6i.large` to `r6i.4xlarge` |
| `DataVolumeSizeGB` | `100` | 50–16000 |
| `KeyPairName` | (blank) | Optional; SSM Session Manager works without one |
| `AllowedHTTPSCidr` | `0.0.0.0/0` | Tighten for private deployments |
| `LicenseJWT` | (blank) | Blank = trial; paste production JWT after purchase |

We deliberately do **not** expose AI provider keys, backup retention, or VPC-adoption parameters at Marketplace launch time — every additional field on the launch form measurably hurts conversion. Customers who need those settings can update them post-launch via the AWS console.

## AMI ID injection workflow

```
After Packer build:
  manifest.json contains 10 AMI IDs (one per region)

Run:
  infra/scripts/update-cfn-mappings.sh manifest.json tier1-quicklaunch.yaml

This rewrites the RegionToAMI mapping in-place:
  us-east-1: { AMI: AMI_ID_PLACEHOLDER }   →   us-east-1: { AMI: ami-0abc... }
  ...

Then submit the updated YAML to the Marketplace Management Portal.
```

The placeholder pattern `AMI_ID_PLACEHOLDER` is searched-and-replaced by the script — easier to review in PRs than per-region SSM parameters or template fragments.

## Local validation before submitting

```bash
# 1. Lint the template.
aws cloudformation validate-template --template-body file://tier1-quicklaunch.yaml

# 2. cfn-lint (catches more than aws CLI does).
pip install cfn-lint
cfn-lint tier1-quicklaunch.yaml

# 3. Dry-run deploy in your test account (replace placeholder AMI IDs first).
sed -i.bak 's/AMI_ID_PLACEHOLDER/ami-0abc.../g' tier1-quicklaunch.yaml
aws cloudformation deploy \
  --stack-name castclone-test \
  --template-file tier1-quicklaunch.yaml \
  --capabilities CAPABILITY_NAMED_IAM
```

The `CAPABILITY_NAMED_IAM` flag is required because we set explicit `RoleName` values (Marketplace allows this for AMI-with-CFN listings, but stack creation in a non-Marketplace context needs the explicit capability).

## What changes between releases

Per-release: `Mappings.RegionToAMI` (new AMI IDs from each Packer build).
Stable across releases: parameter set, resource topology, IAM scope, output names — these are part of the listing's documented contract and changing them forces customer re-launch.
