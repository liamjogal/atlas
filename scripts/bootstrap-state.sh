#!/usr/bin/env bash
# One-time: create the S3 bucket that holds Terraform's state, and write infra/backend.hcl.
# Usage: scripts/bootstrap-state.sh   (needs AWS credentials: aws sso login)
set -euo pipefail
REGION="${AWS_REGION:-us-east-1}"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET="atlas-tfstate-${ACCOUNT}"

if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" >/dev/null
  else
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
  fi
fi
# State contains generated database passwords: versioned, encrypted, never public.
aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

cat > "$(dirname "$0")/../infra/backend.hcl" <<HCL
bucket = "${BUCKET}"
region = "${REGION}"
HCL
echo "State bucket ready: s3://${BUCKET}. Next: cd infra && terraform init -backend-config=backend.hcl"
