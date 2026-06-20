# ---------------------------------------------------------------------------
# IAM role for the query Lambda
# ---------------------------------------------------------------------------
resource "aws_iam_role" "query_lambda_exec" {
  name = "${var.project_name}-query-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "query_lambda_basic" {
  role       = aws_iam_role.query_lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "query_lambda_redshift" {
  name = "${var.project_name}-query-redshift"
  role = aws_iam_role.query_lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "redshift-data:ExecuteStatement",
        "redshift-data:GetStatementResult",
        "redshift-data:DescribeStatement",
        "redshift-serverless:GetCredentials",
      ]
      Resource = "*"
    }]
  })
}

# ---------------------------------------------------------------------------
# Lambda function — query latest weather row via Redshift Spectrum
# ---------------------------------------------------------------------------
resource "aws_lambda_function" "query" {
  function_name    = "${var.project_name}-query"
  role             = aws_iam_role.query_lambda_exec.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  timeout          = 30
  filename         = "${path.module}/../lambda_query/build/query.zip"
  source_code_hash = filebase64sha256("${path.module}/../lambda_query/build/query.zip")

  environment {
    variables = {
      REDSHIFT_WORKGROUP = aws_redshiftserverless_workgroup.main.workgroup_name
      REDSHIFT_DATABASE  = "dev"
    }
  }
}
