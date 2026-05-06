#!/bin/bash
# Pre-pull every container image needed at runtime so customer first-boot has zero pull time.
# Authenticates to ECR if the IMAGE_REGISTRY hostname matches an ECR pattern.
set -euxo pipefail

: "${IMAGE_REGISTRY:?IMAGE_REGISTRY required}"
: "${IMAGE_TAG:?IMAGE_TAG required}"
: "${BUILD_REGION:?BUILD_REGION required}"

# ECR login (only fires for ECR registries).
if echo "$IMAGE_REGISTRY" | grep -qE '\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com'; then
	ECR_HOST=$(echo "$IMAGE_REGISTRY" | cut -d/ -f1)
	ECR_REGION=$(echo "$IMAGE_REGISTRY" | sed -nE 's|.*\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com.*|\1|p')
	aws ecr get-login-password --region "$ECR_REGION" | \
		sudo docker login --username AWS --password-stdin "$ECR_HOST"
fi

# Cast-clone application images.
for IMAGE in cast-clone-backend cast-clone-frontend cast-clone-mcp; do
	sudo docker pull "${IMAGE_REGISTRY}/${IMAGE}:${IMAGE_TAG}"
done

# Base service images (third-party, public Docker Hub).
sudo docker pull postgres:16
sudo docker pull neo4j:5-community
sudo docker pull redis:7-alpine
sudo docker pull minio/minio:latest
sudo docker pull caddy:2-alpine

# Audit list (helps debug AMI bloat — large images = large AMIs = slow Marketplace replication).
sudo docker images
echo "--- Total docker image storage:"
sudo du -sh /var/lib/docker
