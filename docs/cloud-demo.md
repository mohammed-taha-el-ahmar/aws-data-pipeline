# Cloud Demo Runbook

Step-by-step guide to demo the full AWS pipeline live. Total time from a
clean account: **~25 minutes** (mostly waiting on Glue and Redshift Serverless).

---

## Prerequisites checklist

Before starting, confirm:

- [ ] AWS CLI configured: `aws sts get-caller-identity` returns your account ID
- [ ] Terraform ≥ 1.7 installed: `terraform -version`
- [ ] uv installed: `uv --version`
- [ ] Docker running (optional — only needed for local tests): `docker info`
- [ ] Redshift Serverless is enabled in your AWS account and region
      (check: AWS Console → Redshift Serverless → if you see a setup wizard, it's not yet enabled)

---

## Phase 1 — Provision (~12 min)

```bash
# 1. Install dev deps and verify the ingest logic works locally (~30 s)
uv sync --group dev
uv run python -m shared.ingest
# Expected: JSON blob with temperature_2m, wind_speed_10m, relative_humidity_2m

# 2. Package the Lambda zip (~5 s)
./build.sh
# Expected: "Built lambda_ingest/build/ingest.zip"

# 3. Configure Terraform
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars: change aws_region and redshift_admin_password at minimum

# 4. Init and apply (~8–12 min — Redshift Serverless is slow to provision)
terraform init
terraform apply
# Type "yes" when prompted
# ⚠️  The aws_redshiftserverless_workgroup resource takes 5–10 min — this is normal
```

### What to show after apply

```bash
# Show all resource outputs in one shot
terraform output

# Highlight the key ones:
terraform output data_lake_bucket          # S3 bucket name
terraform output ingest_lambda             # Lambda function name
terraform output glue_workflow             # Glue workflow name
terraform output redshift_spectrum_role_arn
```

---

## Phase 2 — Trigger the ingest Lambda (~1 min)

The Lambda runs automatically every hour (EventBridge). For a demo, trigger it manually:

```bash
# From the project root (not terraform/)
LAMBDA=$(cd terraform && terraform output -raw ingest_lambda)
BUCKET=$(cd terraform && terraform output -raw data_lake_bucket)

aws lambda invoke \
  --function-name "$LAMBDA" \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/lambda-out.json

cat /tmp/lambda-out.json
# Expected: {"statusCode": 200, "key": "raw/year=.../month=.../day=.../<ts>.json"}
```

### Verify the raw object landed in S3

```bash
aws s3 ls s3://$BUCKET/raw/ --recursive
# Expected: one .json file under raw/year=/month=/day=/
```

---

## Phase 3 — Run the Glue workflow (~8–10 min)

```bash
WORKFLOW=$(cd terraform && terraform output -raw glue_workflow)

# Start the workflow (crawl raw → ETL transform → crawl processed)
aws glue start-workflow-run --name "$WORKFLOW"
# Note the RunId in the output

# Poll status (run this every 60 s until Status = COMPLETED)
aws glue get-workflow-run \
  --name "$WORKFLOW" \
  --run-id <RunId> \
  --query 'Run.{Status:Status,StartedOn:StartedOn}'
```

**Expected timeline:**

| Step | Duration | What's happening |
|---|---|---|
| Raw crawler | ~2 min | Glue infers schema from the JSON in `raw/`, creates/updates the catalog table |
| ETL job | ~4 min | Spark reads the catalog table, flattens to 6 columns, writes Parquet to `processed/` |
| Processed crawler | ~2 min | Glue catalogs the Parquet in `processed/`, creates/updates the catalog table |

### Verify Parquet landed in S3

```bash
aws s3 ls s3://$BUCKET/processed/ --recursive
# Expected: one or more .parquet files under processed/
```

---

## Phase 4 — Redshift Spectrum query (one-time setup + query)

### 4a. Create the external schema (run once)

After `terraform apply`, Terraform prints the exact SQL — just copy and paste:

```bash
cd terraform && terraform output spectrum_schema_sql
```

Run the printed SQL in the **AWS Console → Redshift → Query Editor v2**:
1. Open Query Editor v2
2. Connect to the workgroup: `terraform output -raw redshift_workgroup_name`
3. Select database: `dev`
4. Paste and run the `CREATE EXTERNAL SCHEMA` statement

> ℹ️ If you see **"Schema 'spectrum' already exists"** — the schema was
> already created by a previous run. This is fine; skip to the grants step.

### 4b. Grant the query Lambda access (run once, right after 4a)

The `CREATE EXTERNAL SCHEMA` is owned by the admin user. The Lambda's
Data API calls run as a separate IAM-mapped Redshift user and need explicit
`USAGE` + `SELECT` grants.

```bash
cd terraform && terraform output spectrum_grant_sql
```

Paste and run the printed SQL in the same Query Editor v2 session:

```sql
GRANT USAGE ON SCHEMA spectrum TO "IAMR:data-pipeline-query-exec";
GRANT SELECT ON ALL TABLES IN SCHEMA spectrum TO "IAMR:data-pipeline-query-exec";
```

> ⚠️ **If you skip this step** the API returns
> `"permission denied for schema spectrum"` even though the schema exists.

### 4c. Query the processed data

```sql
-- Check the external schema was created
SELECT * FROM svv_external_schemas WHERE schemaname = 'spectrum';

-- Browse the processed table
SELECT * FROM spectrum.processed LIMIT 10;

-- Latest reading (what the frontend would show)
SELECT
    ingested_at,
    latitude,
    longitude,
    temperature_c,
    wind_speed_kmh,
    humidity_pct
FROM spectrum.processed
ORDER BY ingested_at DESC
LIMIT 1;
```

### 4c (alternative) — Redshift Data API (no console needed)

```bash
WG=$(cd terraform && terraform output -raw redshift_workgroup_name)

# Submit the query
STMT_ID=$(aws redshift-data execute-statement \
  --workgroup-name "$WG" \
  --database dev \
  --sql "SELECT * FROM spectrum.processed ORDER BY ingested_at DESC LIMIT 1;" \
  --query 'Id' --output text)

echo "Statement ID: $STMT_ID"

# Wait ~5 s, then retrieve results
aws redshift-data get-statement-result --id "$STMT_ID"
```

---

## Phase 5 — Frontend (~1 min)

The frontend is deployed automatically by `terraform apply` — no manual
URL editing needed. Terraform reads `frontend/index.html`, replaces the
placeholder URL with the real API Gateway endpoint, and uploads the result
to an S3 static website bucket.

```bash
# Get the live URLs
cd terraform
terraform output frontend_url       # → http://<bucket>.s3-website.eu-west-3.amazonaws.com
terraform output api_gateway_url    # → https://<id>.execute-api.eu-west-3.amazonaws.com/latest
```

Open the frontend URL in a browser. You should see:

```
Paris — Live Weather (AWS pipeline)
────────────────────────────────────
Temperature    21.5 °C
Wind speed      6.2 km/h
Humidity          55 %
────────────────────────────────────
Last updated: 2026-06-20T11:00:00+00:00
```

> ⚠️ **If the card shows "spectrum schema not ready":** the one-time
> `CREATE EXTERNAL SCHEMA` SQL in Phase 4a has not been run yet.
> Complete Phase 4a first, then reload the page.

> ⚠️ **If the card shows "no processed data yet":** the Glue workflow
> (Phase 3) has not completed yet. Wait for it to finish, then reload.

### Test the API directly

```bash
API=$(cd terraform && terraform output -raw api_gateway_url)
curl -s "$API" | python -m json.tool
# Expected JSON with temperature_c, wind_speed_kmh, humidity_pct, ingested_at
```

### Test the frontend locally (without AWS)

```bash
# One command — serves both the HTML (with API URL replaced) and the mock JSON
uv run python scripts/mock_api.py
# Then open http://localhost:8080 in your browser
```

---

## Phase 6 — Teardown

```bash
cd terraform
terraform destroy
# Type "yes" — all S3 objects are deleted automatically (force_destroy = true
# if set, otherwise you may need to empty the bucket first)
```

### If S3 bucket is not empty

```bash
BUCKET=$(terraform output -raw data_lake_bucket)
aws s3 rm s3://$BUCKET --recursive
terraform destroy
```

---

## What the full demo proves

| Layer | What you show |
|---|---|
| **Ingest** | Lambda invocation → S3 object with `raw/year=/month=/day=/` path |
| **Schema management** | Glue Catalog table created automatically by the crawler from raw JSON |
| **Transform** | Parquet files in `processed/` with the flattened 6-column schema |
| **Warehouse** | Redshift Spectrum querying Parquet directly — no COPY/load step |
| **Infrastructure** | All of the above provisioned from a single `terraform apply` |
| **Local testing** | Unit tests (moto) + CI (GitHub Actions) pass without AWS credentials |

---

## Timing cheat sheet

| Step | Expected duration |
|---|---|
| `./build.sh` | < 10 s |
| `terraform apply` | 8–12 min (Redshift Serverless cold start) |
| Lambda invoke (manual) | < 5 s |
| Glue raw crawler | ~2 min |
| Glue ETL job | ~4 min |
| Glue processed crawler | ~2 min |
| Redshift Spectrum query | < 5 s (after schema created) |
| `terraform destroy` | ~5 min |

**Total (first run): ~25 min**
**Repeat run (infra already up): ~10 min** (skip apply, trigger Lambda + Glue manually)
