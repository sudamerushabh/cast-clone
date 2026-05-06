#!/bin/bash
# Sign a trial license JWT for the Marketplace AMI bake.
#
# Calls the license-infra/ signing API (defined in license-infra/lambda/sign_license/handler.py).
# The JWT we mint here has expires_in_days=365 — a long backstop. The actual 14-day trial window
# is enforced by the application using the EC2 instance's first_boot_at timestamp, not the JWT exp.
# This way customers launching the AMI months after publish still get a usable 14-day trial.
#
# Usage:
#   SIGNING_API_URL=https://api.example.com ./sign-trial-license.sh > /tmp/trial.jwt
#   SIGNING_API_KEY=...                     # optional, if your API Gateway requires an API key

set -euo pipefail

: "${SIGNING_API_URL:?SIGNING_API_URL required (e.g., https://abc123.execute-api.us-east-1.amazonaws.com/prod/sign)}"
SIGNING_API_KEY="${SIGNING_API_KEY:-}"

PAYLOAD=$(cat <<'JSON'
{
  "installation_id": "marketplace-trial",
  "customer_name": "Marketplace Trial",
  "customer_email": "trial@cast-clone.invalid",
  "customer_organization": "AWS Marketplace Trial",
  "tier": "trial",
  "loc_limit": 1000000,
  "expires_in_days": 365,
  "notes": "AMI-baked trial JWT — application enforces 14-day clock from first_boot_at"
}
JSON
)

CURL_AUTH=()
if [ -n "$SIGNING_API_KEY" ]; then
	CURL_AUTH=(-H "x-api-key: $SIGNING_API_KEY")
fi

RESPONSE=$(curl -fsS \
	-X POST \
	-H "Content-Type: application/json" \
	"${CURL_AUTH[@]}" \
	-d "$PAYLOAD" \
	"$SIGNING_API_URL")

# Lambda returns { "token": "...", "jti": "...", "expires_at": <unix> }.
# When fronted by API Gateway, that response is wrapped — handle both shapes.
TOKEN=$(echo "$RESPONSE" | jq -r '.token // (.body | fromjson | .token) // empty')

if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then
	echo "ERROR: failed to extract token from response" >&2
	echo "$RESPONSE" >&2
	exit 1
fi

echo "$TOKEN"
