output "data_lake_bucket" {
  value = aws_s3_bucket.data_lake.bucket
}

output "glue_database" {
  value = aws_glue_catalog_database.lake.name
}

output "glue_workflow" {
  value = aws_glue_workflow.pipeline.name
}

output "redshift_workgroup_endpoint" {
  value = aws_redshiftserverless_workgroup.main.endpoint
}

output "redshift_spectrum_role_arn" {
  value = aws_iam_role.redshift_spectrum.arn
}

output "ingest_lambda" {
  value = aws_lambda_function.ingest.function_name
}
