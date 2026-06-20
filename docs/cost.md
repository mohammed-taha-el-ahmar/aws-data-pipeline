# Cost Estimate

> All prices are for **eu-west-3 (Paris)**, June 2026.
> AWS prices vary by ~10–15 % across regions — adjust if you deploy elsewhere.
> Figures are estimates; always check the [AWS Pricing Calculator](https://calculator.aws)
> for exact numbers before committing to production spend.

---

## TL;DR

| Scenario | Estimated cost |
|---|---|
| 25-minute demo, destroy immediately | **~$0.25 – $0.65** |
| Left running 24 hours (Glue runs hourly) | **~$4 – $14 / day** |
| Left running 1 month | **~$120 – $420 / month** |

The wide range comes from Glue's billing minimum per job run (see below).
The **only meaningful ongoing cost is the scheduled Glue workflow** — if you
stop it or destroy the infrastructure, the rest is negligible.

---

## Per-service breakdown

### Lambda (ingest + query)

| Dimension | Value |
|---|---|
| Free tier | 1 M requests + 400 K GB-seconds / month |
| Demo invocations | ~10 total (ingest × 3, query × 7) |
| Duration per call | ≤ 30 s × 128 MB = 3.75 GB-seconds each |
| Demo total GB-seconds | ~38 |

38 GB-seconds is < 0.01 % of the free tier. **Cost: $0.00**

---

### S3 (data lake + frontend)

| Object | Size |
|---|---|
| Raw JSON (1 ingestion) | ~2 KB |
| Processed Parquet | ~5 KB |
| Glue script | ~4 KB |
| `index.html` | ~5 KB |

Total storage: < 20 KB. API calls: ~30 PUTs + GETs.

**Cost: < $0.01** (essentially $0)

---

### EventBridge (ingest schedule)

Scheduled rules targeting Lambda are free.

**Cost: $0.00**

---

### Glue Data Catalog

First 1 M objects and 1 M requests per month are free.
The demo creates 1 database and 2 tables.

**Cost: $0.00**

---

### Glue ETL + Crawlers — main cost driver

AWS Glue 4.0 billing: **$0.50 / DPU-hour** (eu-west-3), with a
**10-minute minimum** per job/crawler run.

#### Resources per workflow run

| Step | DPUs | Actual duration | Billed duration | Cost |
|---|---|---|---|---|
| Raw crawler | 2 | ~2 min | 10 min (minimum) | $0.17 |
| ETL job (`G.1X` × 2 workers + 1 driver) | 3 | ~4 min | 10 min (minimum) | $0.25 |
| Processed crawler | 2 | ~2 min | 10 min (minimum) | $0.17 |
| **Per workflow run** | | | | **~$0.58** |

> The 10-minute minimum means even tiny datasets cost the same as a
> 10-minute run. This is intentional — Glue is designed for large batch
> workloads, not frequent small jobs.

#### Workflow runs over time

| Period | Workflow runs | Glue cost |
|---|---|---|
| 1 demo run (manual trigger) | 1 | ~$0.58 |
| Hourly schedule, 24 h | 24 | **~$14** |
| Hourly schedule, 7 days | 168 | **~$97** |
| Hourly schedule, 30 days | 720 | **~$418** |

**Optimistic case** (if AWS bills actual duration, not the 10-min minimum
for short runs — some community reports suggest this for Glue 4.0):

| Step | Actual duration | Optimistic cost |
|---|---|---|
| Raw crawler | 2 min | $0.03 |
| ETL job | 4 min | $0.10 |
| Processed crawler | 2 min | $0.03 |
| **Per workflow run** | | **~$0.17** |

| Period | Optimistic | Conservative |
|---|---|---|
| Demo (1 run) | ~$0.17 | ~$0.58 |
| 24 h | ~$4 | ~$14 |
| 30 days | ~$120 | ~$420 |

---

### Redshift Serverless

**Billing model:** charged per RPU-second *only during query execution*.
There is **no charge for idle time** — the workgroup sitting dormant
costs nothing.

| Dimension | Value |
|---|---|
| Base capacity | 8 RPUs |
| Price | ~$0.40 / RPU-hour (eu-west-3) = $0.000111 / RPU-second |
| Price per 8-RPU-second | $0.00089 |

#### Demo queries (rough estimate)

| Query | Duration | Cost |
|---|---|---|
| `CREATE EXTERNAL SCHEMA` | ~5 s | $0.004 |
| `SELECT * FROM spectrum.processed LIMIT 10` | ~10 s | $0.007 |
| Query Lambda calls (×5) | ~5 s each | $0.022 |
| **Demo total** | ~55 s | **~$0.04** |

**Idle cost (no queries running): $0.00**

Storage: < 1 MB of Parquet stored in the namespace → < $0.01/month.

---

### API Gateway HTTP API v2

| Dimension | Value |
|---|---|
| Price | $1.00 / 1 M calls |
| Demo calls | ~10 |

**Cost: < $0.01**

---

### CloudWatch Logs

Lambda writes a few KB of logs. First 5 GB/month free.

**Cost: $0.00**

---

## Full demo cost summary

| Service | Demo (25 min) | 24 h left running |
|---|---|---|
| Lambda | $0.00 | $0.00 |
| S3 | <$0.01 | <$0.01 |
| EventBridge | $0.00 | $0.00 |
| Glue Catalog | $0.00 | $0.00 |
| **Glue ETL + Crawlers** | $0.17 – $0.58 | $4 – $14 |
| **Redshift Serverless** | ~$0.04 | ~$0.04 (idle) |
| API Gateway | <$0.01 | <$0.01 |
| CloudWatch | $0.00 | $0.00 |
| **Total** | **~$0.25 – $0.65** | **~$4 – $14** |

---

## ⚠️ Cost risk: the scheduled Glue trigger

The Glue workflow runs **every hour** (`cron(15 * * * ? *)`). If you
`terraform apply` and then forget about it:

- **After 6 hours:** ~$3.50 – $3.50
- **After 24 hours:** ~$4 – $14
- **After 1 week:** ~$28 – $97

### How to stop the Glue schedule without destroying everything

```bash
# Disable the scheduled trigger (stops hourly runs, keeps all resources)
aws glue stop-trigger --name "data-pipeline-start-raw-crawl"

# Re-enable it later
aws glue start-trigger --name "data-pipeline-start-raw-crawl"

# Or trigger one workflow run on demand without the schedule
WORKFLOW=$(cd terraform && terraform output -raw glue_workflow)
aws glue start-workflow-run --name "$WORKFLOW"
```

---

## Teardown = zero cost

After `terraform destroy`, all compute resources are deleted. The only
remaining charge would be S3 if any objects remain (Terraform uses
`force_destroy = true` on both buckets, so they are emptied and deleted
automatically).

```bash
cd terraform
terraform destroy
# Cost after this point: $0.00
```

---

## How to keep costs minimal for a longer-lived demo

| Action | Daily saving |
|---|---|
| Disable the Glue scheduled trigger (see above) | ~$4 – $14 |
| Reduce Glue workers to the minimum (`number_of_workers = 2`) | Already at minimum |
| Switch Glue schedule from hourly to daily | ~$3.50 – $12 |
| Use `G.025X` worker type (Glue 4.0 Flex) instead of `G.1X` | ~60 % Glue saving |

### Optional: switch to Glue Flex execution for the ETL job

Add this to `aws_glue_job.transform` in `terraform/main.tf` to use
lower-cost spot-backed flex workers (not guaranteed start time, but
fine for non-time-critical demo pipelines):

```hcl
execution_class = "FLEX"   # ~34 % cheaper than STANDARD
```

---

## AWS Free Tier eligibility

If your account is within its **12-month free tier** period:

| Service | Free tier benefit |
|---|---|
| Lambda | 1 M requests + 400 K GB-seconds / month |
| S3 | 5 GB storage + 20 K GETs + 2 K PUTs / month |
| CloudWatch | 10 custom metrics, 5 GB logs / month |
| API Gateway | 1 M API calls / month |

Glue and Redshift Serverless are **not included** in the free tier.
Lambda, S3, CloudWatch, and API Gateway are effectively free for this demo
under the free tier.
