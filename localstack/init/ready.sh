#!/bin/bash
# Runs automatically inside the LocalStack container once all services are ready.
# awslocal = aws CLI pre-configured to point at http://localhost:4566.

set -euo pipefail

BUCKET="data-pipeline-local"
REGION="eu-west-3"

echo "→ Creating S3 data-lake bucket: $BUCKET"
awslocal s3 mb "s3://$BUCKET" --region "$REGION"

echo "→ Pre-creating prefix placeholders"
awslocal s3api put-object --bucket "$BUCKET" --key "raw/"       > /dev/null
awslocal s3api put-object --bucket "$BUCKET" --key "processed/" > /dev/null

echo "✅ LocalStack init complete — bucket: $BUCKET"
