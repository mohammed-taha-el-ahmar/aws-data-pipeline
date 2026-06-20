#!/usr/bin/env bash
# bootstrap.sh — one-time setup of Terraform remote state backend.
#
# Creates:
#   - S3 bucket for tfstate (versioned, encrypted, private)
#   - DynamoDB table for state locking (prevents concurrent applies)
#
# Run ONCE before `terraform init` with an S3 backend:
#   cd terraform
#   ../scripts/bootstrap-tf-backend.sh
#
# The script is idempotent — safe to re-run.

set -euo pipefail

# ── Config — edit these if needed ────────────────────────────────────────────
REGION="${AWS_DEFAULT_REGION:-eu-west-3}"
PROJECT="${TF_VAR_project_name:-data-pipeline}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

BUCKET="${PROJECT}-tfstate-${ACCOUNT_ID}"
DYNAMO_TABLE="${PROJECT}-tf-locks"
# ─────────────────────────────────────────────────────────────────────────────

echo "Bootstrap Terraform backend"
echo "  Bucket : s3://$BUCKET"
echo "  DynamoDB: $DYNAMO_TABLE"
echo "  Region  : $REGION"
echo ""

# ── S3 bucket ─────────────────────────────────────────────────────────────────
if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "✓ S3 bucket already exists: $BUCKET"
else
  echo "→ Creating S3 bucket: $BUCKET"
  if [ "$REGION" = "us-east-1" ]; then
    # us-east-1 does not accept a LocationConstraint
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
  else
    aws s3api create-bucket \
      --bucket "$BUCKET" \
      --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION"
  fi
fi

echo "→ Enabling versioning"
aws s3api put-bucket-versioning \
  --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled

echo "→ Enabling AES-256 server-side encryption"
aws s3api put-bucket-encryption \
  --bucket "$BUCKET" \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "AES256"
      }
    }]
  }'

echo "→ Blocking public access"
aws s3api put-public-access-block \
  --bucket "$BUCKET" \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# ── DynamoDB table (state locking) ────────────────────────────────────────────
if aws dynamodb describe-table --table-name "$DYNAMO_TABLE" --region "$REGION" 2>/dev/null; then
  echo "✓ DynamoDB table already exists: $DYNAMO_TABLE"
else
  echo "→ Creating DynamoDB lock table: $DYNAMO_TABLE"
  aws dynamodb create-table \
    --table-name "$DYNAMO_TABLE" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION"

  echo "→ Waiting for table to be active..."
  aws dynamodb wait table-exists --table-name "$DYNAMO_TABLE" --region "$REGION"
fi

# ── Print backend config ──────────────────────────────────────────────────────
cat <<EOF

✅ Bootstrap complete. Add this backend block to terraform/providers.tf
   (replace the commented-out block that is already there):

  backend "s3" {
    bucket         = "$BUCKET"
    key            = "data-pipeline/terraform.tfstate"
    region         = "$REGION"
    dynamodb_table = "$DYNAMO_TABLE"
    encrypt        = true
  }

Then run:
  cd terraform
  terraform init   # will prompt to migrate existing local state → S3
EOF
