# ---------------------------------------------------------------------------
# Frontend — S3 static website hosting
#
# Terraform injects the real API Gateway URL into index.html at deploy time
# using replace(), so no manual edit of the HTML is required after apply.
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "frontend" {
  bucket        = "${var.project_name}-frontend-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_website_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id

  index_document { suffix = "index.html" }
  error_document { key    = "index.html" }
}

resource "aws_s3_bucket_policy" "frontend_public" {
  bucket     = aws_s3_bucket.frontend.id
  depends_on = [aws_s3_bucket_public_access_block.frontend]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "PublicReadGetObject"
      Effect    = "Allow"
      Principal = "*"
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.frontend.arn}/*"
    }]
  })
}

# Read index.html from disk, swap the placeholder URL for the real API
# Gateway endpoint, and upload the result as the S3 object.
# This replaces "https://example.invalid/latest" with the actual invoke URL.
resource "aws_s3_object" "frontend_index" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "index.html"
  content_type = "text/html"
  depends_on   = [aws_s3_bucket_policy.frontend_public]

  content = replace(
    file("${path.module}/../frontend/index.html"),
    "https://example.invalid/latest",
    "${trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")}/latest"
  )
}
