# ---------------------------------------------------------------------------
# Landing zone
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "data_lake" {
  bucket = "${var.project_name}-data-lake-${data.aws_caller_identity.current.account_id}"
}

# ---------------------------------------------------------------------------
# Lambda: ingest — scheduled hourly, writes raw JSON to s3://.../raw/
# ---------------------------------------------------------------------------
resource "aws_iam_role" "lambda_exec" {
  name = "${var.project_name}-lambda-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_s3" {
  name = "${var.project_name}-lambda-s3"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
      Resource = [
        aws_s3_bucket.data_lake.arn,
        "${aws_s3_bucket.data_lake.arn}/*"
      ]
    }]
  })
}

resource "aws_lambda_function" "ingest" {
  function_name    = "${var.project_name}-ingest"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  timeout          = 30
  filename         = "${path.module}/../lambda_ingest/build/ingest.zip"
  source_code_hash = filebase64sha256("${path.module}/../lambda_ingest/build/ingest.zip")

  environment {
    variables = {
      DATA_LAKE_BUCKET = aws_s3_bucket.data_lake.bucket
    }
  }
}

resource "aws_cloudwatch_event_rule" "ingest_schedule" {
  name                = "${var.project_name}-ingest-schedule"
  schedule_expression = "rate(1 hour)"
}

resource "aws_cloudwatch_event_target" "ingest_target" {
  rule = aws_cloudwatch_event_rule.ingest_schedule.name
  arn  = aws_lambda_function.ingest.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.ingest_schedule.arn
}

# ---------------------------------------------------------------------------
# Glue Data Catalog + IAM role
# ---------------------------------------------------------------------------
resource "aws_glue_catalog_database" "lake" {
  name = replace("${var.project_name}_lake", "-", "_")
}

resource "aws_iam_role" "glue" {
  name = "${var.project_name}-glue-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "glue.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy" "glue_s3" {
  name = "${var.project_name}-glue-s3"
  role = aws_iam_role.glue.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
      Resource = [
        aws_s3_bucket.data_lake.arn,
        "${aws_s3_bucket.data_lake.arn}/*"
      ]
    }]
  })
}

# ---------------------------------------------------------------------------
# Glue Crawlers — raw/ (JSON, from Lambda) and processed/ (Parquet, from the
# Glue ETL job below)
# ---------------------------------------------------------------------------
resource "aws_glue_crawler" "raw" {
  name          = "${var.project_name}-raw-crawler"
  role          = aws_iam_role.glue.arn
  database_name = aws_glue_catalog_database.lake.name

  s3_target {
    path = "s3://${aws_s3_bucket.data_lake.bucket}/raw/"
  }

  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }
}

resource "aws_glue_crawler" "processed" {
  name          = "${var.project_name}-processed-crawler"
  role          = aws_iam_role.glue.arn
  database_name = aws_glue_catalog_database.lake.name

  s3_target {
    path = "s3://${aws_s3_bucket.data_lake.bucket}/processed/"
  }

  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }
}

# ---------------------------------------------------------------------------
# Glue ETL job — Spark transform: raw/ (via Catalog) -> processed/ (Parquet)
# ---------------------------------------------------------------------------
resource "aws_s3_object" "glue_script" {
  bucket = aws_s3_bucket.data_lake.bucket
  key    = "scripts/transform_job.py"
  source = "${path.module}/../glue/jobs/transform_job.py"
  etag   = filemd5("${path.module}/../glue/jobs/transform_job.py")
}

resource "aws_glue_job" "transform" {
  name     = "${var.project_name}-transform"
  role_arn = aws_iam_role.glue.arn

  command {
    name            = "glueetl"
    script_location = "s3://${aws_s3_bucket.data_lake.bucket}/${aws_s3_object.glue_script.key}"
    python_version  = "3"
  }

  default_arguments = {
    "--job-language"    = "python"
    "--SOURCE_DATABASE" = aws_glue_catalog_database.lake.name
    # NOTE: the crawler names tables after the deepest S3 prefix by default.
    # For s3://<bucket>/raw/ that's typically "raw" — verify in the Glue
    # console after the first crawl and adjust if it differs (e.g. if the
    # date-partitioned layout produces a different inferred name).
    "--SOURCE_TABLE"   = "raw"
    "--TARGET_S3_PATH" = "s3://${aws_s3_bucket.data_lake.bucket}/processed/"
  }

  glue_version      = "4.0"
  worker_type       = "G.1X"
  number_of_workers = 2
  max_retries       = 0
}

# ---------------------------------------------------------------------------
# Glue Workflow — chains: crawl(raw) -> transform job -> crawl(processed)
# ---------------------------------------------------------------------------
resource "aws_glue_workflow" "pipeline" {
  name = "${var.project_name}-workflow"
}

resource "aws_glue_trigger" "start_raw_crawl" {
  name          = "${var.project_name}-start-raw-crawl"
  type          = "SCHEDULED"
  schedule      = "cron(15 * * * ? *)" # hourly, 15 min after the ingest Lambda
  workflow_name = aws_glue_workflow.pipeline.name
  enabled       = true

  actions {
    crawler_name = aws_glue_crawler.raw.name
  }
}

resource "aws_glue_trigger" "run_transform_after_crawl" {
  name          = "${var.project_name}-run-transform"
  type          = "CONDITIONAL"
  workflow_name = aws_glue_workflow.pipeline.name
  enabled       = true

  predicate {
    conditions {
      crawler_name = aws_glue_crawler.raw.name
      crawl_state  = "SUCCEEDED"
    }
  }

  actions {
    job_name = aws_glue_job.transform.name
  }
}

resource "aws_glue_trigger" "crawl_processed_after_transform" {
  name          = "${var.project_name}-crawl-processed"
  type          = "CONDITIONAL"
  workflow_name = aws_glue_workflow.pipeline.name
  enabled       = true

  predicate {
    conditions {
      job_name = aws_glue_job.transform.name
      state    = "SUCCEEDED"
    }
  }

  actions {
    crawler_name = aws_glue_crawler.processed.name
  }
}

# ---------------------------------------------------------------------------
# Redshift Serverless — with an IAM role attached for Redshift Spectrum
# (queries processed/ directly via the Glue Data Catalog, no load step)
# ---------------------------------------------------------------------------
resource "aws_iam_role" "redshift_spectrum" {
  name = "${var.project_name}-redshift-spectrum"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "redshift.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "redshift_spectrum_access" {
  name = "${var.project_name}-redshift-spectrum-access"
  role = aws_iam_role.redshift_spectrum.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["glue:GetDatabase", "glue:GetTable", "glue:GetTables", "glue:GetPartitions"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.data_lake.arn,
          "${aws_s3_bucket.data_lake.arn}/*"
        ]
      }
    ]
  })
}

resource "aws_redshiftserverless_namespace" "main" {
  namespace_name      = "${var.project_name}-ns"
  admin_username      = var.redshift_admin_username
  admin_user_password = var.redshift_admin_password
  db_name             = "dev"
  iam_roles           = [aws_iam_role.redshift_spectrum.arn]
}

resource "aws_redshiftserverless_workgroup" "main" {
  namespace_name = aws_redshiftserverless_namespace.main.namespace_name
  workgroup_name = "${var.project_name}-wg"
  base_capacity  = 8 # smallest billable unit (RPUs)
}

# TODO (one-time, run against Redshift via Query Editor v2 or the Data API):
#
#   CREATE EXTERNAL SCHEMA spectrum
#   FROM DATA CATALOG
#   DATABASE '<aws_glue_catalog_database.lake.name>'
#   IAM_ROLE '<aws_iam_role.redshift_spectrum.arn>';
#
#   SELECT * FROM spectrum.processed LIMIT 10;
#
# (table name = whatever the processed crawler names it, typically "processed")

# TODO: aws_s3_bucket_website_configuration for frontend/, or CloudFront.
# TODO: API Gateway HTTP API + Lambda (or Redshift Data API) to expose
# "latest reading" as JSON for frontend/index.html to consume.
