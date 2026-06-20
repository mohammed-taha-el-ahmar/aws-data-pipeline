# AWS Data Pipeline — Lambda + Glue + Redshift Spectrum

> Part of a multi-cloud data engineering pattern — see `PORTFOLIO.md` in the
> companion repos for the cross-cloud comparison. Same `shared/` ingest +
> transform logic as `gcp-data-pipeline`, `azure-data-pipeline`, and
> `k8s-airflow-data-platform`.

`API -> Lambda -> S3 -> Glue (Crawler + ETL + Crawler) -> Redshift Spectrum -> Front`

## Why this design

Lambda and Glue are doing the jobs they're each best at, not duplicating each
other:

- **Lambda** — cheap, frequent, lightweight: poll an API on a schedule and
  drop the response in S3. No cluster to manage for something this small.
- **Glue** — cataloging + bulk transform: a Crawler infers schema from the
  landed JSON (including the date partitions), a Spark ETL job reshapes it
  into Parquet, and a second Crawler catalogs the result.
- **Redshift Spectrum** — queries the Parquet in `processed/` directly via
  the Glue Data Catalog as an external table. No load/COPY step, no
  Glue<->Redshift VPC networking — just an IAM role.

This is a small-scale stand-in for a common real pattern: land raw data
cheaply, use Glue for schema management and batch transformation, and let the
warehouse query the lake directly for data that doesn't need to be
duplicated into native tables.

## Components

| Resource | Purpose |
|---|---|
| `aws_s3_bucket.data_lake` | Landing zone — `raw/` (JSON) and `processed/` (Parquet) |
| `aws_lambda_function.ingest` | Hourly (EventBridge), writes to `raw/` |
| `aws_glue_catalog_database.lake` | Glue Data Catalog database |
| `aws_glue_crawler.raw` / `.processed` | Infer schema from `raw/` and `processed/` |
| `aws_glue_job.transform` | Spark ETL: `raw/` (via Catalog) -> `processed/` (Parquet) |
| `aws_glue_workflow.pipeline` + triggers | Chains crawl(raw) -> transform -> crawl(processed) |
| `aws_redshiftserverless_*` | Warehouse, with an IAM role for Spectrum |
| `frontend/index.html` | Static dashboard placeholder |

## Setup

### Prerequisites
- [uv](https://docs.astral.sh/uv/) — dependency manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- [Terraform](https://developer.hashicorp.com/terraform/install) ≥ 1.7
- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) configured — see [`docs/aws-credentials.md`](docs/aws-credentials.md) for step-by-step setup

### Local environment

```bash
# Install all dev dependencies (boto3, pytest, moto) into .venv
uv sync --group dev

# Verify the ingest + transform logic against the live Open-Meteo API
uv run python -m shared.ingest
```

### Cloud deployment

```bash
# 1. Set up credentials (one-time — see docs/aws-credentials.md)
cp .env.example .env
# Edit .env: set AWS_PROFILE to your named profile (e.g. data-pipeline-poc)
# and TF_VAR_redshift_admin_password to a real password

# 2. Export env vars into your shell — required before every Terraform command
source .env
aws sts get-caller-identity   # verify credentials are working

# 3. Package both Lambda functions
./build.sh

# 4. Provision infrastructure (from project root — source .env first)
cd terraform
cp terraform.tfvars.example terraform.tfvars   # edit aws_region + Redshift password
terraform init
terraform apply
```

> ⚠️ **Always `source .env` in the same shell before running Terraform.**
> Variables must be *exported* to child processes — `source` without `export`
> in each line won't work. All lines in `.env` use `export` for this reason.

After the first `apply`, the Glue workflow runs on its own schedule (raw
crawl → transform → processed crawl). You can also start it on demand:

```bash
# Trigger the Glue workflow manually via AWS CLI
aws glue start-workflow-run --name "<project>-workflow"

# Check its status
aws glue get-workflow-run \
  --name "<project>-workflow" \
  --run-id <run-id> \
  --query 'Run.Status'
```

See [`docs/commands.md`](docs/commands.md) for the full command reference and
[`docs/troubleshooting.md`](docs/troubleshooting.md) for common issues.

## TODOs to take this from scaffold to working pipeline

- [ ] After the first raw crawl, check the table name Glue assigned in
      `aws_glue_catalog_database.lake` (usually `raw`) and confirm it matches
      `--SOURCE_TABLE` in `aws_glue_job.transform`.
- [x] ~~One-time SQL against Redshift~~ — done: run these once in Query Editor v2
      after the first Glue workflow completes:
      ```bash
      cd terraform
      terraform output spectrum_schema_sql   # CREATE EXTERNAL SCHEMA
      terraform output spectrum_grant_sql    # GRANT access to the query Lambda
      ```
      See Phase 4 in [`docs/cloud-demo.md`](docs/cloud-demo.md).
- [x] ~~Build a small endpoint (Lambda behind API Gateway) that runs that query
      and returns the latest row as JSON~~ — done: `lambda_query/` +
      `terraform/query_lambda.tf` + `terraform/api_gateway.tf`
- [x] ~~Host `frontend/index.html` on S3 static website hosting~~ — done:
      `terraform/frontend.tf` (Terraform injects the API URL at deploy time)

See [`docs/cloud-demo.md`](docs/cloud-demo.md) for the full step-by-step runbook.

## Teardown

```bash
cd terraform
terraform destroy
```

## Docs

| Document | Contents |
|---|---|
| [`docs/cloud-demo.md`](docs/cloud-demo.md) | **Step-by-step live demo runbook with timing** |
| [`docs/aws-credentials.md`](docs/aws-credentials.md) | AWS credentials setup — long-term keys, SSO, named profiles |
| [`docs/cost.md`](docs/cost.md) | AWS cost estimate — demo vs left-running scenarios |
| [`docs/architecture.md`](docs/architecture.md) | Mermaid data-flow diagrams + design decisions |
| [`docs/commands.md`](docs/commands.md) | Full command reference (uv, Terraform, AWS CLI, Glue) |
| [`docs/local-testing.md`](docs/local-testing.md) | LocalStack + moto local testing guide |
| [`docs/troubleshooting.md`](docs/troubleshooting.md) | Common issues and fixes |

