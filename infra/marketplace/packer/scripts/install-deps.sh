#!/bin/bash
# Install runtime dependencies into the AMI: docker engine, docker compose plugin, jq.
set -euxo pipefail

sudo dnf install -y docker jq

sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user

# AL2023 ships docker but not the compose v2 plugin — install it manually.
DOCKER_CFG_DIR=/usr/local/lib/docker/cli-plugins
sudo mkdir -p "$DOCKER_CFG_DIR"
sudo curl -fsSL https://github.com/docker/compose/releases/download/v2.30.3/docker-compose-linux-x86_64 \
	-o "$DOCKER_CFG_DIR/docker-compose"
sudo chmod +x "$DOCKER_CFG_DIR/docker-compose"

# Sanity checks (Packer fails the build if these don't exit 0).
docker --version
docker compose version
jq --version
aws --version
