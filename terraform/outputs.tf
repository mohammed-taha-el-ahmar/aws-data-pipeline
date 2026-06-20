output "data_lake_bucket" {
  value       = aws_s3_bucket.data_lake.bucket
  description = "S3 bucket name for raw/ and processed/ prefixes"
}

output "glue_database" {
  value       = aws_glue_catalog_database.lake.name
  description = "Glue Data Catalog database name — use in CREATE EXTERNAL SCHEMA"
}

output "glue_workflow" {
  value       = aws_glue_workflow.pipeline.name
  description = "Glue workflow name — use with aws glue start-workflow-run"
}

output "glue_raw_crawler" {
  value       = aws_glue_crawler.raw.name
  description = "Glue raw crawler name"
}

output "glue_transform_job" {
  value       = aws_glue_job.transform.name
  description = "Glue ETL job name"
}

output "ingest_lambda" {
  value       = aws_lambda_function.ingest.function_name
  description = "Lambda function name — use with aws lambda invoke"
}

output "redshift_workgroup_endpoint" {
  value       = aws_redshiftserverless_workgroup.main.endpoint
  description = "Redshift Serverless workgroup endpoint (host + port)"
}

output "redshift_workgroup_name" {
  value       = aws_redshiftserverless_workgroup.main.workgroup_name
  description = "Redshift Serverless workgroup name — needed for Data API calls"
}

output "redshift_namespace_name" {
  value       = aws_redshiftserverless_namespace.main.namespace_name
  description = "Redshift Serverless namespace name"
}

output "redshift_spectrum_role_arn" {
  value       = aws_iam_role.redshift_spectrum.arn
  description = "IAM role ARN for Redshift Spectrum — use in CREATE EXTERNAL SCHEMA"
}

output "query_lambda" {
  value       = aws_lambda_function.query.function_name
  description = "Query Lambda function name"
}

output "api_gateway_url" {
  value       = "${trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")}/latest"
  description = "API Gateway endpoint — GET this URL to receive the latest weather JSON"
}

output "frontend_url" {
  value       = "http://${aws_s3_bucket_website_configuration.frontend.website_endpoint}"
  description = "S3 static website URL for the frontend dashboard"
}

# ─── Convenience: copy-paste-ready SQL ───────────────────────────────────────
output "spectrum_schema_sql" {
  description = "Run this once in Redshift Query Editor v2 after the first Glue workflow run"
  value       = <<-SQL
    CREATE EXTERNAL SCHEMA spectrum
    FROM DATA CATALOG
    DATABASE '${aws_glue_catalog_database.lake.name}'
    IAM_ROLE '${aws_iam_role.redshift_spectrum.arn}';
  SQL
}

output "spectrum_grant_sql" {
  description = "Run this once after CREATE EXTERNAL SCHEMA — grants the query Lambda's IAM user access to the schema"
  value       = <<-SQL
    GRANT USAGE ON SCHEMA spectrum TO "IAMR:${aws_iam_role.query_lambda_exec.name}";
    GRANT SELECT ON ALL TABLES IN SCHEMA spectrum TO "IAMR:${aws_iam_role.query_lambda_exec.name}";
  SQL
}
