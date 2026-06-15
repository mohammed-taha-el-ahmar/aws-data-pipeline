#!/usr/bin/env bash
# Packages shared/ + lambda_ingest/handler.py into a zip Terraform can deploy.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$ROOT_DIR/lambda_ingest/build"
PKG_DIR="$BUILD_DIR/package"

rm -rf "$BUILD_DIR"
mkdir -p "$PKG_DIR"

cp "$ROOT_DIR/lambda_ingest/handler.py" "$PKG_DIR/"
cp -r "$ROOT_DIR/shared" "$PKG_DIR/shared"

if [ -s "$ROOT_DIR/lambda_ingest/requirements.txt" ]; then
  pip install -r "$ROOT_DIR/lambda_ingest/requirements.txt" -t "$PKG_DIR" --quiet --break-system-packages || true
fi

(cd "$PKG_DIR" && zip -r "../ingest.zip" . > /dev/null)
echo "Built $BUILD_DIR/ingest.zip"
