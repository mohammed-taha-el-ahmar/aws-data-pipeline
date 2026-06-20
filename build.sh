#!/usr/bin/env bash
# Packages both Lambda functions into zips that Terraform can deploy.
#   lambda_ingest/build/ingest.zip  — ingest handler + shared/
#   lambda_query/build/query.zip    — query handler (boto3 is in the Lambda runtime)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Ingest Lambda ────────────────────────────────────────────────────────────
BUILD_DIR="$ROOT_DIR/lambda_ingest/build"
PKG_DIR="$BUILD_DIR/package"

rm -rf "$BUILD_DIR"
mkdir -p "$PKG_DIR"

cp "$ROOT_DIR/lambda_ingest/handler.py" "$PKG_DIR/"
cp -r "$ROOT_DIR/shared" "$PKG_DIR/shared"

if [ -s "$ROOT_DIR/lambda_ingest/requirements.txt" ]; then
  uv pip install -r "$ROOT_DIR/lambda_ingest/requirements.txt" --target "$PKG_DIR" --quiet
fi

(cd "$PKG_DIR" && zip -r "../ingest.zip" . > /dev/null)
echo "Built $BUILD_DIR/ingest.zip"

# ── Query Lambda ─────────────────────────────────────────────────────────────
QUERY_BUILD_DIR="$ROOT_DIR/lambda_query/build"
QUERY_PKG_DIR="$QUERY_BUILD_DIR/package"

rm -rf "$QUERY_BUILD_DIR"
mkdir -p "$QUERY_PKG_DIR"

cp "$ROOT_DIR/lambda_query/handler.py" "$QUERY_PKG_DIR/"

if [ -s "$ROOT_DIR/lambda_query/requirements.txt" ]; then
  uv pip install -r "$ROOT_DIR/lambda_query/requirements.txt" --target "$QUERY_PKG_DIR" --quiet
fi

(cd "$QUERY_PKG_DIR" && zip -r "../query.zip" . > /dev/null)
echo "Built $QUERY_BUILD_DIR/query.zip"
