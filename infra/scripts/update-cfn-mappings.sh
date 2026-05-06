#!/bin/bash
# Replace AMI_ID_PLACEHOLDER tokens in a CloudFormation template with the AMI IDs
# from a Packer manifest. Run this after every `packer build`.
#
# Usage:
#   ./update-cfn-mappings.sh \
#     infra/marketplace/packer/manifest.json \
#     infra/marketplace/cloudformation/tier1-quicklaunch.yaml

set -euo pipefail

MANIFEST="${1:?manifest.json path required (output of packer build)}"
CFN_TEMPLATE="${2:?CloudFormation template path required}"

# Packer's manifest.json stores the artifact_id as "region:ami,region:ami,...".
ARTIFACT_ID=$(jq -r '.builds[0].artifact_id' "$MANIFEST")

if [ -z "$ARTIFACT_ID" ] || [ "$ARTIFACT_ID" = "null" ]; then
	echo "ERROR: could not read .builds[0].artifact_id from $MANIFEST" >&2
	exit 1
fi

# Portable in-place sed (works on both GNU and BSD/macOS).
sed_inplace() {
	local file="$1"
	shift
	local tmp
	tmp=$(mktemp)
	sed "$@" "$file" > "$tmp"
	mv "$tmp" "$file"
}

cp "$CFN_TEMPLATE" "${CFN_TEMPLATE}.bak"

UPDATED=0
IFS=',' read -ra PAIRS <<< "$ARTIFACT_ID"
for PAIR in "${PAIRS[@]}"; do
	REGION="${PAIR%%:*}"
	AMI_ID="${PAIR##*:}"

	# Match: "<region>:      { AMI: <something> }"
	# Replace the <something> token (placeholder or stale ami-XXXX).
	sed_inplace "$CFN_TEMPLATE" -E \
		"s|(${REGION}:[[:space:]]*\\{[[:space:]]*AMI:[[:space:]]*)[A-Za-z0-9_-]+([[:space:]]*\\})|\\1${AMI_ID}\\2|"

	UPDATED=$((UPDATED + 1))
	echo "  ${REGION} → ${AMI_ID}"
done

echo "Updated ${UPDATED} region(s) in ${CFN_TEMPLATE} (backup at ${CFN_TEMPLATE}.bak)."

# Sanity check: any remaining placeholders?
if grep -q AMI_ID_PLACEHOLDER "$CFN_TEMPLATE"; then
	echo "WARNING: ${CFN_TEMPLATE} still contains AMI_ID_PLACEHOLDER tokens." >&2
	echo "These regions were not in the Packer manifest:" >&2
	grep -E '^\s+[a-z]+-[a-z]+-[0-9]+:.*AMI_ID_PLACEHOLDER' "$CFN_TEMPLATE" | sed 's/^/  /' >&2
fi
