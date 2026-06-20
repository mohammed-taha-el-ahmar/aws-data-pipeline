# Troubleshooting

## Local / uv

### `ssl.SSLCertVerificationError` when running `python -m shared.ingest`

**Cause:** macOS Python (from python.org or Homebrew) doesn't trust the
system root certificates by default unless you run the *Install Certificates*
script.

**Fix:** Use `uv run` instead of `python` directly. `uv`'s managed Python
bundles `certifi` and uses it automatically.

```bash
# ✅ works
uv run python -m shared.ingest

# ❌ may fail on macOS stock Python
python -m shared.ingest
```

If you prefer a plain `python` invocation, run the certificate installer once:

```bash
/Applications/Python\ 3.12/Install\ Certificates.command
```

---

### `ModuleNotFoundError: No module named 'shared'`

**Cause:** Running `python lambda_ingest/handler.py` directly instead of as a
module from the project root, or the `.venv` is not active.

**Fix:** Always run from the project root, via `uv run`:

```bash
# from /aws-data-pipeline/
uv run python -m shared.ingest
```

---

### `.venv` missing or stale packages

```bash
# Recreate from scratch
rm -rf .venv
uv sync --group dev
```

---

### `build.sh` fails with `uv: command not found`

Install `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# then reload your shell
source ~/.zshrc
```

---

## Terraform

### `Error: No valid credential sources found`

**Cause A — `source .env` without `export`:**
The most common cause. `source .env` sets variables in the current shell but
doesn't *export* them to child processes. Terraform runs as a subprocess and
never sees `AWS_PROFILE` or the access keys.

**Fix:** Every variable in `.env` must use `export`:
```bash
# ✅ correct — Terraform inherits this
export AWS_PROFILE=data-pipeline-poc

# ❌ wrong — Terraform never sees this
AWS_PROFILE=data-pipeline-poc
```

Check your `.env` has `export` on every line, then re-source:
```bash
grep "^AWS_PROFILE" .env          # should show: export AWS_PROFILE=...
source .env
aws sts get-caller-identity       # must succeed before running Terraform
cd terraform && terraform plan
```

**Cause B — wrong or missing profile name:**
The profile in `~/.aws/credentials` doesn't match `AWS_PROFILE` in `.env`.

```bash
# List all configured profiles
aws configure list-profiles

# Check which profile .env is setting
grep AWS_PROFILE .env

# Verify the profile works
AWS_PROFILE=<your-profile> aws sts get-caller-identity
```

Then update `.env` so `AWS_PROFILE` matches exactly.

**Cause C — `~/.aws/credentials` doesn't exist yet:**
Run the setup wizard for your profile:
```bash
aws configure --profile data-pipeline-poc
# Enter your Access Key ID, Secret, region (eu-west-3), output format (json)
```
See [`docs/aws-credentials.md`](aws-credentials.md) for the full setup guide.

---

### `Error: Failed to get existing workspaces: S3 bucket does not exist`

**Cause:** You uncommented the `backend "s3"` block in `providers.tf` but
haven't created the S3 bucket yet. Terraform **cannot create its own state
bucket** — it must already exist before `terraform init`.

**Fix:** Run the bootstrap script first:

```bash
source .env
./scripts/bootstrap-tf-backend.sh
# then: terraform init
```

---

### `Error: state data in S3 does not have the expected content`

**Cause:** The S3 key already contains a state file from a different
workspace or a corrupted write.

**Fix:**

```bash
# Option A — pull the current remote state and continue
terraform init -reconfigure

# Option B — start fresh (destructive — only if the state is truly corrupt
# and you can rebuild all resources)
aws s3 rm s3://<tfstate-bucket>/data-pipeline/terraform.tfstate
terraform init
```

---

### `Error: Error acquiring the state lock` / DynamoDB lock not released

**Cause:** A previous `terraform apply` or `plan` was interrupted and left a
lock entry in DynamoDB.

**Fix:**

```bash
# Find the lock ID from the error message, then force-unlock:
terraform force-unlock <LOCK_ID>

# If you don't have the lock ID, find it in DynamoDB:
aws dynamodb scan --table-name "<project>-tf-locks" \
  --query 'Items[].LockID.S'
```

---

### `Error: filename ... does not exist` (Lambda zip not found)

**Cause:** `./build.sh` hasn't been run yet — Terraform expects
`lambda_ingest/build/ingest.zip` to exist before `apply`.

**Fix:**

```bash
./build.sh
cd terraform && terraform apply
```

---

### `terraform apply` times out on `aws_redshiftserverless_workgroup`

**Cause:** Redshift Serverless can take 5–10 minutes to provision.

**Fix:** This is expected — just wait. If it truly fails, check the AWS
console for quota limits (Redshift Serverless is not available in all
regions).

---

### State drift after a manual console change

```bash
# Pull actual AWS state back into the .tfstate
terraform refresh

# Or, for a specific resource
terraform plan -refresh-only -target=aws_lambda_function.ingest
```

---

## Glue

### Workflow run stuck in `RUNNING` with no job activity

1. Go to **Glue → Workflows → \<project\>-workflow → History** and open the
   latest run graph.
2. If the raw crawler node is orange/failed, the raw crawler likely timed out
   or found no files. Check that the Lambda has run at least once:

```bash
aws s3 ls s3://<bucket>/raw/ --recursive
```

3. Trigger the Lambda manually if needed:

```bash
aws lambda invoke \
  --function-name "<project>-ingest" \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/out.json && cat /tmp/out.json
```

---

### Glue ETL job fails with `AnalysisException: Table not found`

**Cause:** The raw crawler hasn't run yet, so the Glue Catalog table doesn't
exist.

**Fix:** Run the raw crawler first, then re-trigger the ETL job:

```bash
aws glue start-crawler --name "<project>-raw-crawler"
# wait for it to finish (~1–2 min), then:
aws glue start-job-run --job-name "<project>-transform"
```

---

### Glue ETL job fails with `--SOURCE_TABLE` mismatch

**Cause:** Glue Crawler names the table after the top-level S3 prefix. If the
bucket name contains hyphens, the table name may differ from `raw`.

**Fix:**

1. Check the actual table name in **Glue → Data Catalog → Tables**.
2. Update the `--SOURCE_TABLE` argument in `terraform/main.tf` under
   `aws_glue_job.transform`'s `default_arguments`:

```hcl
default_arguments = {
  "--SOURCE_TABLE" = "raw"   # ← change to whatever the crawler assigned
  ...
}
```

3. Re-apply: `terraform apply`.

---

### Glue job logs not visible in CloudWatch

By default the Glue job writes to two log groups:

- `/aws-glue/jobs/output` — stdout
- `/aws-glue/jobs/error` — stderr / exceptions

```bash
# Stream error log for the most recent run
aws logs tail /aws-glue/jobs/error --follow --filter-pattern "<job-name>"
```

---

## Redshift Spectrum

### `ERROR: External table "spectrum.processed" does not exist`

**Cause:** The `CREATE EXTERNAL SCHEMA spectrum …` statement hasn't been run
yet, or the processed Glue catalog table doesn't exist.

**Fix:**
1. Confirm the processed Glue table exists: **Glue → Data Catalog → Tables → processed**.
2. If missing, re-run the Glue workflow (Phase 3 in the runbook).
3. If the table exists but the schema is missing, run:
   ```bash
   cd terraform && terraform output spectrum_schema_sql
   ```
   and paste the result into Query Editor v2.

---

### `ERROR: Access denied for IAM role` on Spectrum query

**Cause:** The Redshift Serverless namespace's IAM role doesn't have S3 read
permission on `processed/`.

**Fix:** Confirm the `aws_iam_role_policy.spectrum_s3` resource was applied
by Terraform, then re-attach it:

```bash
terraform apply -target=aws_iam_role_policy.spectrum_s3
```

---

### `ERROR: permission denied for schema spectrum`

**Cause:** The `spectrum` schema exists but the IAM-mapped Redshift user for the
query Lambda (`IAMR:data-pipeline-query-exec`) has not been granted access.
`CREATE EXTERNAL SCHEMA` is owned by the admin user; IAM-mapped users are separate
Redshift principals that need explicit `USAGE` + `SELECT` grants.

The query Lambda returns:
```json
{"error": "permission denied on spectrum schema — run the GRANT SQL (see terraform output spectrum_grant_sql)"}
```

**Fix:** Run the grant SQL once in Query Editor v2 (workgroup `<project>-wg`, database `dev`):

```bash
cd terraform && terraform output spectrum_grant_sql
```

Or paste directly:

```sql
GRANT USAGE ON SCHEMA spectrum TO "IAMR:data-pipeline-query-exec";
GRANT SELECT ON ALL TABLES IN SCHEMA spectrum TO "IAMR:data-pipeline-query-exec";
```

This only needs to be run once per workgroup. If the workgroup is torn down and
recreated (`terraform destroy` + `terraform apply`), the grants must be re-applied.

---

## Frontend

### Dashboard shows "spectrum schema not ready"

**Cause:** Phase 4a (`CREATE EXTERNAL SCHEMA`) hasn't been run yet.

**Fix:** Copy the SQL from `terraform output spectrum_schema_sql` and run it in
Query Editor v2 (workgroup `<project>-wg`, database `dev`). See Phase 4a in
[`docs/cloud-demo.md`](cloud-demo.md).

---

### Dashboard shows "permission denied on spectrum schema"

**Cause:** The schema exists but the query Lambda's IAM user hasn't been
granted access. See [above](#error-permission-denied-for-schema-spectrum).

---

### Dashboard shows "no processed data yet"

**Cause:** The Glue workflow hasn't completed, so there are no rows in
`spectrum.processed`.

**Fix:** Check status and wait for `COMPLETED`:

```bash
source .env
WORKFLOW=$(cd terraform && terraform output -raw glue_workflow)
aws glue list-workflow-runs --name "$WORKFLOW" \
  --query 'Ids[0]' --output text | xargs -I{} \
  aws glue get-workflow-run --name "$WORKFLOW" --run-id {} \
  --query 'Run.{Status:Status}'
```

If no run exists yet, trigger Lambda + Glue manually (Phases 2–3 in the runbook).

---

### API URL has a double slash (`//latest`)

**Cause:** API Gateway `$default` stage's `invoke_url` already ends with `/`,
so naive concatenation produces `//latest`.

**Fix:** Already patched in `terraform/outputs.tf` and `terraform/frontend.tf`
with `trimsuffix(…, "/")`. Re-apply to refresh the S3 object:

```bash
source .env && cd terraform && terraform apply -auto-approve
```

---

### CORS error in the browser console

**Cause:** The Lambda response is missing `Access-Control-Allow-Origin`.

**Fix:** Already present in `lambda_query/handler.py` via `CORS_HEADERS`. If
you're seeing CORS errors, confirm you're calling the correct URL
(`terraform output -raw api_gateway_url`) and that the Lambda was redeployed
after the last handler change (`aws lambda update-function-code …`).
