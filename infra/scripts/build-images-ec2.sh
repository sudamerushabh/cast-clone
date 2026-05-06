#!/bin/bash
# Build cast-clone images on a temporary EC2 instance and push to ECR.
#
# Why on EC2: in-AWS network to ECR is gigabit; pushing 3+ GB images from a laptop
# over residential internet takes ~30 minutes vs ~30 seconds. Build itself is also
# faster (m6i.2xlarge = 8 vCPU + fast EBS).
#
# Usage:
#   VERSION=v0.1.0 ./build-images-ec2.sh
#
# Env vars:
#   VERSION         (required) — tag applied to backend + frontend images
#   AWS_REGION      (default us-east-1)
#   ECR_PREFIX      (default cast-clone)
#   INSTANCE_TYPE   (default m6i.2xlarge — 8 vCPU is sweet spot for backend Dockerfile)

set -euo pipefail

: "${VERSION:?VERSION required (e.g. v0.1.0)}"
AWS_REGION="${AWS_REGION:-us-east-1}"
ECR_PREFIX="${ECR_PREFIX:-cast-clone}"
INSTANCE_TYPE="${INSTANCE_TYPE:-m6i.2xlarge}"
ROLE_NAME="cast-clone-image-builder"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SUFFIX=$(date +%s)
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REGISTRY="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
BUCKET="cast-clone-build-${ACCOUNT_ID}-${SUFFIX}"
TARBALL="/tmp/cast-clone-source-${SUFFIX}.tar.gz"

cleanup() {
  echo "==> Cleanup"
  [ -n "${INSTANCE_ID:-}" ] && aws ec2 terminate-instances --instance-ids "$INSTANCE_ID" --region "$AWS_REGION" >/dev/null 2>&1 || true
  aws s3 rb "s3://${BUCKET}" --force >/dev/null 2>&1 || true
  rm -f "$TARBALL"
}
trap cleanup EXIT

# 1. Tar source. CRITICAL: COPYFILE_DISABLE=1 prevents macOS BSD tar from embedding
# extended attributes as PAX headers — Linux GNU tar would otherwise expand those into
# `._*` AppleDouble files at extract time, which contain null bytes and crash any Python
# loader that globs them (e.g., alembic migration scanning).
echo "==> Tarring source"
COPYFILE_DISABLE=1 tar -czf "$TARBALL" \
  -C "$REPO_ROOT" \
  --exclude='*/node_modules' \
  --exclude='*/.venv' \
  --exclude='*/.next' \
  --exclude='*/dist' \
  --exclude='*/build' \
  --exclude='*/.git' \
  --exclude='*/__pycache__' \
  --exclude='*/.pytest_cache' \
  --exclude='*/.cache' \
  --exclude='*/.mypy_cache' \
  --exclude='*/.ruff_cache' \
  --exclude='*/coverage' \
  --exclude='*/.coverage' \
  --exclude='*/htmlcov' \
  --exclude='*/tsconfig.tsbuildinfo' \
  --exclude='._*' \
  --exclude='.DS_Store' \
  cast-clone-backend cast-clone-frontend
echo "    $(ls -lh "$TARBALL" | awk '{print $5}') tarball"

# 2. Upload source to a transient S3 bucket
echo "==> Uploading source to s3://${BUCKET}"
aws s3 mb "s3://${BUCKET}" --region "$AWS_REGION" >/dev/null
aws s3 cp "$TARBALL" "s3://${BUCKET}/source.tar.gz" --quiet

# 3. Ensure ECR repos exist
echo "==> Ensuring ECR repos"
for REPO in cast-clone-backend cast-clone-frontend cast-clone-mcp; do
  aws ecr describe-repositories --repository-names "${ECR_PREFIX}/${REPO}" --region "$AWS_REGION" >/dev/null 2>&1 || \
    aws ecr create-repository \
      --repository-name "${ECR_PREFIX}/${REPO}" \
      --region "$AWS_REGION" \
      --image-scanning-configuration scanOnPush=true \
      --encryption-configuration encryptionType=AES256 >/dev/null
done

# 4. Ensure IAM role + instance profile (idempotent)
echo "==> Ensuring IAM role ${ROLE_NAME}"
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE_NAME" \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"sts:AssumeRole","Principal":{"Service":"ec2.amazonaws.com"}}]}' >/dev/null
  # PowerUser (not ReadOnly) — the builder needs to PUSH images, not just pull.
  # S3FullAccess — to upload the build log on failure for diagnosis.
  for POLICY in \
    arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore \
    arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser \
    arn:aws:iam::aws:policy/AmazonS3FullAccess; do
    aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "$POLICY"
  done
  aws iam create-instance-profile --instance-profile-name "$ROLE_NAME" >/dev/null
  aws iam add-role-to-instance-profile --instance-profile-name "$ROLE_NAME" --role-name "$ROLE_NAME"
  sleep 12  # IAM eventual consistency
fi

# 5. Launch builder instance
echo "==> Launching ${INSTANCE_TYPE} builder"
AMI_ID=$(aws ec2 describe-images \
  --owners 137112412989 \
  --filters "Name=name,Values=al2023-ami-2023.*-kernel-*-x86_64" "Name=architecture,Values=x86_64" \
  --query 'sort_by(Images,&CreationDate)|[-1].ImageId' --output text --region "$AWS_REGION")
DEFAULT_VPC=$(aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" --query 'Vpcs[0].VpcId' --output text --region "$AWS_REGION")
DEFAULT_SUBNET=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=${DEFAULT_VPC}" "Name=default-for-az,Values=true" --query 'Subnets[0].SubnetId' --output text --region "$AWS_REGION")

USER_DATA=$(cat <<'UDEOF'
#!/bin/bash
set -euxo pipefail
exec > /var/log/builder-bootstrap.log 2>&1
dnf install -y docker
systemctl enable --now docker
echo ready > /var/log/builder-ready
UDEOF
)

INSTANCE_ID=$(aws ec2 run-instances \
  --image-id "$AMI_ID" \
  --instance-type "$INSTANCE_TYPE" \
  --iam-instance-profile Name="$ROLE_NAME" \
  --subnet-id "$DEFAULT_SUBNET" \
  --user-data "$USER_DATA" \
  --metadata-options 'HttpTokens=required,HttpPutResponseHopLimit=2' \
  --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=60,VolumeType=gp3,DeleteOnTermination=true}' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=cast-clone-builder},{Key=Disposable,Value=true}]' \
  --region "$AWS_REGION" \
  --query 'Instances[0].InstanceId' --output text)
echo "    ${INSTANCE_ID}"

aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --region "$AWS_REGION"
echo "==> Waiting for SSM agent"
for _ in $(seq 1 30); do
  if [ "$(aws ssm describe-instance-information --filters "Key=InstanceIds,Values=${INSTANCE_ID}" --query 'InstanceInformationList[0].PingStatus' --output text --region "$AWS_REGION" 2>/dev/null)" = "Online" ]; then
    break
  fi
  sleep 10
done

# Wait for user-data to complete docker install (sentinel file written by user-data).
# Without this, the build command races against `dnf install -y docker` and systemctl
# fails because the docker unit isn't yet known.
echo "==> Waiting for user-data to finish (docker install)"
WAIT_CMD=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --region "$AWS_REGION" \
  --parameters 'commands=["for i in $(seq 1 60); do test -f /var/log/builder-ready && exit 0; sleep 5; done; exit 1"]' \
  --timeout-seconds 600 \
  --query 'Command.CommandId' --output text)
while true; do
  S=$(aws ssm get-command-invocation --command-id "$WAIT_CMD" --instance-id "$INSTANCE_ID" --region "$AWS_REGION" --query Status --output text 2>/dev/null || echo Pending)
  case "$S" in Success|Failed|TimedOut|Cancelled) break ;; esac
  sleep 5
done
[ "$S" = "Success" ] || { echo "user-data didn't finish in time ($S)"; exit 1; }

# 6. Send build command via SSM
echo "==> Building + pushing images on instance"
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --comment "cast-clone image build ${VERSION}" \
  --timeout-seconds 3600 \
  --region "$AWS_REGION" \
  --parameters "commands=[
    \"set -euxo pipefail\",
    \"exec > /var/log/cast-clone-build.log 2>&1\",
    \"systemctl start docker || systemctl restart docker\",
    \"mkdir -p /tmp/build && cd /tmp/build\",
    \"aws s3 cp s3://${BUCKET}/source.tar.gz .\",
    \"tar -xzf source.tar.gz\",
    \"# Defense-in-depth: even though COPYFILE_DISABLE=1 was set at tar time, sweep any AppleDouble files that snuck in.\",
    \"find . -name '._*' -delete || true\",
    \"aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${ECR_REGISTRY}\",
    \"echo === Building backend ===\",
    \"cd /tmp/build/cast-clone-backend\",
    \"docker build -t ${ECR_REGISTRY}/${ECR_PREFIX}/cast-clone-backend:${VERSION} -t ${ECR_REGISTRY}/${ECR_PREFIX}/cast-clone-backend:latest .\",
    \"docker push ${ECR_REGISTRY}/${ECR_PREFIX}/cast-clone-backend:${VERSION}\",
    \"docker push ${ECR_REGISTRY}/${ECR_PREFIX}/cast-clone-backend:latest\",
    \"echo === Building mcp ===\",
    \"cd /tmp/build/cast-clone-backend\",
    \"docker build -f Dockerfile.mcp -t ${ECR_REGISTRY}/${ECR_PREFIX}/cast-clone-mcp:${VERSION} -t ${ECR_REGISTRY}/${ECR_PREFIX}/cast-clone-mcp:latest .\",
    \"docker push ${ECR_REGISTRY}/${ECR_PREFIX}/cast-clone-mcp:${VERSION}\",
    \"docker push ${ECR_REGISTRY}/${ECR_PREFIX}/cast-clone-mcp:latest\",
    \"echo === Building frontend ===\",
    \"cd /tmp/build/cast-clone-frontend\",
    \"docker build --build-arg NEXT_PUBLIC_API_URL= -t ${ECR_REGISTRY}/${ECR_PREFIX}/cast-clone-frontend:${VERSION} -t ${ECR_REGISTRY}/${ECR_PREFIX}/cast-clone-frontend:latest .\",
    \"docker push ${ECR_REGISTRY}/${ECR_PREFIX}/cast-clone-frontend:${VERSION}\",
    \"docker push ${ECR_REGISTRY}/${ECR_PREFIX}/cast-clone-frontend:latest\",
    \"echo === Build done ===\",
    \"docker images --format '{{.Repository}}:{{.Tag}} ({{.Size}})'\"
  ]" \
  --query 'Command.CommandId' --output text)

# 7. Poll for completion
echo "==> Polling build (typical: ~5 min for backend + ~2 min for frontend)"
while true; do
  S=$(aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$AWS_REGION" --query Status --output text 2>/dev/null || echo Pending)
  echo "    [$(date +%H:%M:%S)] $S"
  case "$S" in
    Success) break ;;
    Failed|TimedOut|Cancelled)
      echo "BUILD FAILED ($S) — fetching on-instance log to /tmp/cast-clone-build-${SUFFIX}.log"
      # Copy the build log off the instance before the trap terminates it.
      DUMP_CMD=$(aws ssm send-command \
        --instance-ids "$INSTANCE_ID" \
        --document-name "AWS-RunShellScript" \
        --region "$AWS_REGION" \
        --parameters "commands=[\"aws s3 cp /var/log/cast-clone-build.log s3://${BUCKET}/cast-clone-build-${SUFFIX}.log 2>&1 || tail -100 /var/log/cast-clone-build.log\"]" \
        --query 'Command.CommandId' --output text 2>/dev/null)
      sleep 8
      aws s3 cp "s3://${BUCKET}/cast-clone-build-${SUFFIX}.log" "/tmp/cast-clone-build-${SUFFIX}.log" 2>/dev/null && \
        echo "===== Last 60 lines of on-instance build log =====" && \
        tail -60 "/tmp/cast-clone-build-${SUFFIX}.log"
      echo ""
      echo "===== SSM stderr ====="
      aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$AWS_REGION" --query StandardErrorContent --output text | tail -30
      exit 1
      ;;
  esac
  sleep 30
done

aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$AWS_REGION" --query StandardOutputContent --output text | tail -20

cat <<DONE

✓ Build complete.
  ${ECR_REGISTRY}/${ECR_PREFIX}/cast-clone-backend:${VERSION}
  ${ECR_REGISTRY}/${ECR_PREFIX}/cast-clone-frontend:${VERSION}

Next:
  cd infra/terraform/tiers/tier1-starter
  echo 'image_registry = "${ECR_REGISTRY}/${ECR_PREFIX}"' > terraform.tfvars
  echo 'image_tag      = "${VERSION}"'                  >> terraform.tfvars
  terraform apply
DONE
