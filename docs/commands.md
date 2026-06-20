# Command Reference

## Environment variables

Two env files are provided. Neither contains real secrets.

| File | Purpose | Committed? |
|---|---|---|
| `.env.example` | Template for real AWS development — copy to `.env` and fill in | ✅ Yes |
| `.env.localstack` | Ready-to-use fake credentials for LocalStack | ✅ Yes |
| `.env` | Your real credentials (copied from `.env.example`) | ❌ Gitignored |

### Real AWS setup

```bash
cp .env.example .env
# Edit .env — fill in AWS_PROFILE (or keys), TF_VAR_redshift_admin_password,
# and DATA_LAKE_BUCKET / REDSHIFT_WORKGROUP after terraform apply.

source .env

# Verify credentials
aws sts get-caller-identity
```

### LocalStack setup

```bash
# Start LocalStack
docker compose -f docker-compose.localstack.yml up -d

# Load LocalStack env vars, then run integration/smoke tests
source .env.localstack
uv run pytest tests/integration tests/smoke -v

# Or inline (no persistent shell export):
env $(grep -v '^#' .env.localstack | xargs) uv run pytest tests/integration -v
```

### Fill in Lambda runtime vars after terraform apply

```bash
source .env   # must be sourced first

# Append the Terraform output values to .env
echo "DATA_LAKE_BUCKET=$(cd terraform && terraform output -raw data_lake_bucket)" >> .env
echo "REDSHIFT_WORKGROUP=$(cd terraform && terraform output -raw redshift_workgroup_name)" >> .env

# Now you can invoke the Lambda handler directly without AWS deployment:
uv run python -c "
import json
from lambda_ingest.handler import lambda_handler
print(json.dumps(lambda_handler({}, None), indent=2))
"
```

---

## uv — dependency management

```bash
# Create / refresh the local .venv with all dev deps (boto3, pytest, moto, pytest-cov)
uv sync --group dev

# Also install LocalStack helpers (awslocal CLI)
uv sync --group dev --group localstack

# Install only the Lambda runtime deps (boto3) — lighter, mirrors what build.sh does
uv sync --group lambda

# Add a new dependency
uv add <package>                   # runtime
uv add --dev <package>             # dev-only

# Run any command inside the managed .venv without activating it
uv run python <script.py>
uv run pytest
uv run python -m shared.ingest     # test the ingest logic locally against the live API
```

---

## Testing

```bash
# Run all unit tests (moto — no Docker, no AWS account needed)
uv run pytest tests/unit -v

# Run with coverage report
uv run pytest tests/unit --cov=shared --cov=lambda_ingest --cov-report=term-missing

# Run only a specific test file
uv run pytest tests/unit/test_handler.py -v

# Run integration tests (requires LocalStack — see LocalStack section below)
uv run pytest tests/integration -v

# Run everything (unit tests pass; integration tests auto-skip if LocalStack is down)
uv run pytest -v
```

---

## LocalStack — local AWS emulator (S3 + Lambda)

> See [`docs/local-testing.md`](local-testing.md) for full details and service coverage.

```bash
# Start LocalStack in the background (Docker required)
docker compose -f docker-compose.localstack.yml up -d

# Wait for it to be ready (~10 s), then check health
curl http://localhost:4566/_localstack/health | python -m json.tool

# Run integration tests against LocalStack
uv run pytest tests/integration -v

# Use awslocal (aws CLI pre-pointed at localhost:4566)
awslocal s3 ls
awslocal s3 ls s3://data-pipeline-local/ --recursive
awslocal s3 cp s3://data-pipeline-local/raw/<key> /tmp/sample.json
cat /tmp/sample.json | python -m json.tool

# View LocalStack logs
docker compose -f docker-compose.localstack.yml logs -f

# Stop and remove LocalStack
docker compose -f docker-compose.localstack.yml down

# Wipe persisted state (volumes) for a clean slate
docker compose -f docker-compose.localstack.yml down -v
```

---

## Local development

```bash
# Fetch live weather data from Open-Meteo and print the raw record
uv run python -m shared.ingest

# Run tests
uv run pytest -v

# Run the Lambda handler locally (needs AWS credentials for the S3 write)
DATA_LAKE_BUCKET=my-bucket uv run python -c "
import json
from lambda_ingest.handler import lambda_handler
print(json.dumps(lambda_handler({}, None), indent=2))
"
```

---

## build.sh — Lambda packaging

```bash
# Package shared/ + lambda_ingest/handler.py into lambda_ingest/build/ingest.zip
./build.sh

# Inspect the contents of the zip
unzip -l lambda_ingest/build/ingest.zip
```

---

## Terraform

### Optional: set up remote state backend first (S3 + DynamoDB)

> Skip this for a solo demo — local state is fine.
> Do it if you'll run `terraform apply` from multiple machines or want state history.

```bash
# 1. Create the S3 bucket + DynamoDB lock table (ONE TIME, from project root)
source .env
./scripts/bootstrap-tf-backend.sh
# The script prints the exact backend "s3" { ... } block to paste

# 2. Uncomment the backend "s3" block in terraform/providers.tf
#    (use the values printed by the script above)

# 3. Re-initialise — Terraform will offer to migrate local state → S3
cd terraform && terraform init
# Answer "yes" when prompted to copy existing state
```

### Regular Terraform workflow

```bash
cd terraform

# First-time setup (local state — no bootstrap needed)
cp terraform.tfvars.example terraform.tfvars   # then edit the Redshift password
terraform init

# Preview changes
terraform plan

# Apply
terraform apply

# Show all outputs (S3 bucket name, Redshift endpoint, Spectrum role ARN, etc.)
terraform output

# Tear everything down
terraform destroy

# Format all .tf files in place
terraform fmt -recursive

# Validate configuration without connecting to AWS
terraform validate
```

---

## AWS CLI — Lambda

```bash
# Invoke the ingest Lambda manually and print its response
aws lambda invoke \
  --function-name "<project>-ingest" \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/lambda-out.json \
  && cat /tmp/lambda-out.json

# Tail Lambda logs in real time
aws logs tail /aws/lambda/<project>-ingest --follow

# Update the Lambda code without re-running terraform (useful during iteration)
aws lambda update-function-code \
  --function-name "<project>-ingest" \
  --zip-file fileb://lambda_ingest/build/ingest.zip
```

---

## AWS CLI — S3

```bash
# List all objects in the landing zone
aws s3 ls s3://<bucket>/raw/ --recursive

# Download a specific raw record to inspect it
aws s3 cp s3://<bucket>/raw/year=2026/month=06/day=20/<timestamp>.json /tmp/sample.json
cat /tmp/sample.json | python -m json.tool

# List the processed Parquet files
aws s3 ls s3://<bucket>/processed/ --recursive
```

---

## AWS CLI — Glue

```bash
# Start the full pipeline workflow (crawl raw → transform → crawl processed)
aws glue start-workflow-run --name "<project>-workflow"

# List recent workflow runs and their status
aws glue list-workflow-runs --name "<project>-workflow"

# Get the status of a specific run
aws glue get-workflow-run \
  --name "<project>-workflow" \
  --run-id <run-id> \
  --query 'Run.{Status:Status,StartedOn:StartedOn,ErrorMessage:ErrorMessage}'

# Start only the raw crawler (useful for testing after new data lands)
aws glue start-crawler --name "<project>-raw-crawler"

# Check crawler status
aws glue get-crawler --name "<project>-raw-crawler" \
  --query 'Crawler.{State:State,LastCrawl:LastCrawl}'

# Start only the Glue ETL job
aws glue start-job-run --job-name "<project>-transform"

# Tail the most recent Glue job log
aws glue get-job-runs --job-name "<project>-transform" \
  --query 'JobRuns[0].{State:JobRunState,LogGroupName:LogGroupName,Id:Id}'
```

---

## Redshift Serverless (one-time SQL)

Run these once in the **Query Editor v2** (or via the Data API) after the
first `terraform apply` and the first Glue workflow run.

```sql
-- 1. Create the external schema that maps to the Glue Data Catalog
CREATE EXTERNAL SCHEMA spectrum
FROM DATA CATALOG
DATABASE '<glue-database-name>'        -- matches var.project_name in terraform.tfvars
IAM_ROLE '<redshift-spectrum-role-arn>';  -- from: terraform output redshift_spectrum_role_arn

-- 2. Verify the processed table is visible
SELECT * FROM spectrum.processed LIMIT 10;

-- 3. Latest observation
SELECT * FROM spectrum.processed ORDER BY ingested_at DESC LIMIT 1;
```

---

## Frontend

```bash
# Open the dashboard locally in your default browser
open frontend/index.html

# Deploy to S3 static website hosting (after enabling it in Terraform)
aws s3 sync frontend/ s3://<frontend-bucket>/ --delete

# Invalidate CloudFront cache after a frontend update
aws cloudfront create-invalidation \
  --distribution-id <distribution-id> \
  --paths "/*"
```
