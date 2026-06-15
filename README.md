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

```bash
# 1. Package the ingest Lambda (bundles shared/ + handler.py)
./build.sh

# 2. Provision infrastructure
cd terraform
cp terraform.tfvars.example terraform.tfvars   # edit the Redshift password
terraform init
terraform apply
```

After the first `apply`, the Glue workflow runs on its own schedule (raw
crawl -> transform -> processed crawl). You can also start it on demand from
the Glue console (Workflows -> `<project>-workflow` -> Run).

## TODOs to take this from scaffold to working pipeline

- [ ] After the first raw crawl, check the table name Glue assigned in
      `aws_glue_catalog_database.lake` (usually `raw`) and confirm it matches
      `--SOURCE_TABLE` in `aws_glue_job.transform`.
- [ ] One-time SQL against Redshift (Query Editor v2 or Data API):
      ```sql
      CREATE EXTERNAL SCHEMA spectrum
      FROM DATA CATALOG
      DATABASE '<glue database name>'
      IAM_ROLE '<redshift spectrum role arn — see terraform output>';
      ```
      Then `SELECT * FROM spectrum.processed LIMIT 10;`
- [ ] Build a small endpoint (Lambda behind API Gateway, or the Redshift
      Data API) that runs that query and returns the latest row as JSON, and
      wire its URL into `frontend/index.html`.
- [ ] Host `frontend/index.html` on S3 static website hosting / CloudFront.

## Teardown

```bash
cd terraform
terraform destroy
```
