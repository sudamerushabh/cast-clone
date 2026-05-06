#!/bin/bash
# Build and push cast-clone container images to your private ECR.
# These images become the source for the Marketplace AMI bake (via Packer's pull-images.sh)
# and for direct Terraform installs (via the EC2 instance's first-boot pull).
#
# Usage:
#   VERSION=v0.1.0 ECR_PRIVATE=123456789012.dkr.ecr.us-east-1.amazonaws.com/cast-clone \
#     ./publish-images.sh

set -euo pipefail

: "${VERSION:?VERSION required (e.g. v0.1.0)}"
: "${ECR_PRIVATE:?ECR_PRIVATE required (e.g. 123.dkr.ecr.us-east-1.amazonaws.com/cast-clone)}"

ECR_HOST=$(echo "$ECR_PRIVATE" | cut -d/ -f1)
ECR_REGION=$(echo "$ECR_PRIVATE" | sed -nE 's|.*\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com.*|\1|p')

if [ -z "$ECR_REGION" ]; then
	echo "ERROR: ECR_PRIVATE does not look like an ECR URL" >&2
	exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# 1. Login to ECR.
aws ecr get-login-password --region "$ECR_REGION" | \
	docker login --username AWS --password-stdin "$ECR_HOST"

# 2. Ensure repos exist (idempotent).
for REPO in cast-clone-backend cast-clone-frontend cast-clone-mcp; do
	aws ecr describe-repositories \
		--repository-names "${ECR_PRIVATE##*/}/${REPO}" \
		--region "$ECR_REGION" >/dev/null 2>&1 || \
	aws ecr create-repository \
		--repository-name "${ECR_PRIVATE##*/}/${REPO}" \
		--region "$ECR_REGION" \
		--image-scanning-configuration scanOnPush=true \
		--encryption-configuration encryptionType=AES256
done

# 3. Build + push each component.
build_and_push() {
	local name=$1 dir=$2 dockerfile=${3:-Dockerfile}
	local versioned="${ECR_PRIVATE}/${name}:${VERSION}"
	local latest="${ECR_PRIVATE}/${name}:latest"

	echo "==> Building $name from $dir/$dockerfile"
	docker build \
		--platform linux/amd64 \
		-t "$versioned" \
		-t "$latest" \
		-f "${REPO_ROOT}/${dir}/${dockerfile}" \
		"${REPO_ROOT}/${dir}"

	echo "==> Pushing $versioned"
	docker push "$versioned"
	docker push "$latest"
}

build_and_push "cast-clone-backend"  "cast-clone-backend"
build_and_push "cast-clone-frontend" "cast-clone-frontend"
# build_and_push "cast-clone-mcp"      "cast-clone-backend" "Dockerfile.mcp"   # uncomment when MCP image is split out

cat <<SUMMARY

Done. Images pushed to:
  ${ECR_PRIVATE}/cast-clone-backend:${VERSION}
  ${ECR_PRIVATE}/cast-clone-frontend:${VERSION}

Next step:
  cd infra/marketplace/packer
  packer build \\
    -var "image_registry=${ECR_PRIVATE}" \\
    -var "image_tag=${VERSION}" \\
    -var "version=${VERSION}" \\
    -var "trial_license_jwt=\$(SIGNING_API_URL=... ../../scripts/sign-trial-license.sh)" \\
    tier1-monolith.pkr.hcl
SUMMARY
