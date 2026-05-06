#!/bin/bash
# Cast-Clone T1 runtime bootstrap. Lives at /opt/cast-clone/bootstrap.sh inside the AMI.
# Invoked by the CloudFormation stack's user-data with the per-stack secret ARNs as env vars.
#
# Required env vars (passed by user-data):
#   REGION                          - the deploy region
#   PG_PASSWORD_SECRET_ARN          - secret holding Postgres password
#   NEO4J_PASSWORD_SECRET_ARN       - secret holding Neo4j password
#   LICENSE_JWT_SECRET_ARN          - secret holding license JWT (or 'TRIAL_PLACEHOLDER')
#
# Optional env vars (default to empty / Bedrock):
#   AI_PROVIDER                     - 'bedrock' (default), 'anthropic', or 'openai'
#   AWS_REGION                      - defaults to REGION; consumed by boto3 + Pydantic Settings
#                                     so the app and AWS SDK both use the same region.
#                                     Bedrock auth uses the EC2 instance role via IMDSv2 — no
#                                     static AWS keys are needed or used by default.
#   ANTHROPIC_API_KEY_SECRET_ARN    - empty disables
#   OPENAI_API_KEY_SECRET_ARN       - empty disables

set -euxo pipefail
exec > >(tee -a /var/log/cast-clone/bootstrap.log | logger -t cast-clone -s 2>/dev/console) 2>&1

DATA_DIR=/var/lib/cast-clone
APP_DIR=/opt/cast-clone

: "${REGION:?REGION env var required}"
: "${PG_PASSWORD_SECRET_ARN:?PG_PASSWORD_SECRET_ARN required}"
: "${NEO4J_PASSWORD_SECRET_ARN:?NEO4J_PASSWORD_SECRET_ARN required}"
: "${LICENSE_JWT_SECRET_ARN:?LICENSE_JWT_SECRET_ARN required}"
: "${AI_PROVIDER:=bedrock}"
: "${AWS_REGION:=$REGION}"
: "${ANTHROPIC_API_KEY_SECRET_ARN:=}"
: "${OPENAI_API_KEY_SECRET_ARN:=}"

# 1. Locate + format + mount the EBS data volume.
# Race-tolerant: CloudFormation attaches the data volume slightly after instance launch,
# so user-data may run before the device appears. Poll up to 120s.
DATA_DEV=""
for attempt in $(seq 1 60); do
	DATA_DEV=$(lsblk -ndpo NAME,TYPE | awk '$2 == "disk" && $1 != "/dev/nvme0n1" && $1 != "/dev/xvda" {print $1; exit}')
	[ -n "$DATA_DEV" ] && break
	echo "Waiting for EBS data volume (attempt $attempt/60)..."
	sleep 2
done

if [ -z "$DATA_DEV" ]; then
	echo "FATAL: could not locate EBS data volume after 120s" >&2
	exit 1
fi
echo "Data volume detected: $DATA_DEV"

mkdir -p "$DATA_DIR"
if ! blkid "$DATA_DEV" >/dev/null 2>&1; then
	mkfs.xfs "$DATA_DEV"
fi
DATA_UUID=$(blkid -s UUID -o value "$DATA_DEV")
if ! grep -q "$DATA_UUID" /etc/fstab; then
	echo "UUID=$DATA_UUID $DATA_DIR xfs defaults,nofail 0 2" >> /etc/fstab
fi
mount -a

mkdir -p "$DATA_DIR"/{postgres,neo4j,redis,minio,archives,backups,license}
mkdir -p "$APP_DIR/certs"

# 2. Self-signed TLS cert (10-year validity). Only generated once.
if [ ! -f "$APP_DIR/certs/server.crt" ]; then
	TOKEN=$(curl -fsS -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
	PUBLIC_IP=$(curl -fsS -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4 || echo "127.0.0.1")
	openssl req -x509 -nodes -newkey rsa:4096 -days 3650 \
		-keyout "$APP_DIR/certs/server.key" \
		-out    "$APP_DIR/certs/server.crt" \
		-subj   "/CN=$PUBLIC_IP/O=Cast-Clone/C=US" \
		-addext "subjectAltName=IP:$PUBLIC_IP,DNS:cast-clone.local"
	chmod 600 "$APP_DIR/certs/server.key"
fi

# 3. Fetch secrets.
fetch_secret() {
	local arn="$1"
	if [ -z "$arn" ]; then
		echo ""
		return 0
	fi
	aws secretsmanager get-secret-value --region "$REGION" --secret-id "$arn" --query SecretString --output text 2>/dev/null || echo ""
}

PG_PASSWORD=$(fetch_secret "$PG_PASSWORD_SECRET_ARN")
NEO4J_PASSWORD=$(fetch_secret "$NEO4J_PASSWORD_SECRET_ARN")
LICENSE_JWT=$(fetch_secret "$LICENSE_JWT_SECRET_ARN")
ANTHROPIC_API_KEY=$(fetch_secret "$ANTHROPIC_API_KEY_SECRET_ARN")
OPENAI_API_KEY=$(fetch_secret "$OPENAI_API_KEY_SECRET_ARN")

# 4. Trial license fallback: when the secret holds the placeholder, use the
# AMI-baked JWT. The JWT's exp is a long backstop (365 days from sign time);
# the actual 14-day clock is enforced by the app via first_boot_at below.
if [ "$LICENSE_JWT" = "TRIAL_PLACEHOLDER" ] && [ -f /etc/cast-clone/trial-license.jwt ]; then
	LICENSE_JWT=$(cat /etc/cast-clone/trial-license.jwt)
fi

# 5. Record first-boot timestamp on the data volume so it survives instance replacement.
LICENSE_STATE="$DATA_DIR/license-state.json"
LICENSE_FILE="$DATA_DIR/license/license.jwt"
if [ ! -f "$LICENSE_STATE" ]; then
	if [ -z "$LICENSE_JWT" ] || [ "$LICENSE_JWT" = "TRIAL_PLACEHOLDER" ]; then
		LICENSE_SOURCE=trial
	else
		LICENSE_SOURCE=production
	fi
	printf '{"first_boot_at":"%s","license_source":"%s"}\n' \
		"$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$LICENSE_SOURCE" > "$LICENSE_STATE"
fi

# 5a. Seed the license file IF a real JWT is available (production secret OR baked trial).
# Default flow is customer uploads via the web UI at /settings/license; this seeding only
# pre-populates the trial license on a Marketplace AMI's first boot, OR honors an operator
# who pre-set a real JWT in Secrets Manager.
if [ -n "$LICENSE_JWT" ] && [ "$LICENSE_JWT" != "TRIAL_PLACEHOLDER" ] && [ ! -f "$LICENSE_FILE" ]; then
	echo "$LICENSE_JWT" > "$LICENSE_FILE"
	chmod 600 "$LICENSE_FILE"
	echo "License file seeded at $LICENSE_FILE"
fi

# 6. Write .env (consumed by docker compose for variable substitution into service env).
# Note: LICENSE_JWT is intentionally NOT exported — the app reads license from
# LICENSE_FILE_PATH on the persistent volume, not from environment.
umask 077
cat > "$APP_DIR/.env" <<ENV_EOF
POSTGRES_PASSWORD=$PG_PASSWORD
NEO4J_PASSWORD=$NEO4J_PASSWORD
AI_PROVIDER=$AI_PROVIDER
AWS_REGION=$AWS_REGION
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
OPENAI_API_KEY=$OPENAI_API_KEY
ENV_EOF
umask 022

# 7. Start. Images are pre-baked into the AMI, so no pull required.
cd "$APP_DIR"
docker compose up -d

# 8. systemd unit so containers restart on reboot.
if [ ! -f /etc/systemd/system/cast-clone.service ]; then
	cat > /etc/systemd/system/cast-clone.service <<'UNIT_EOF'
[Unit]
Description=Cast-Clone monolith
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/cast-clone
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down

[Install]
WantedBy=multi-user.target
UNIT_EOF
	systemctl daemon-reload
	systemctl enable cast-clone.service
fi

echo "Cast-Clone bootstrap complete."
