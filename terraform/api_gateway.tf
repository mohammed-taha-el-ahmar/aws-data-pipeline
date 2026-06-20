# ---------------------------------------------------------------------------
# HTTP API (API Gateway v2) — single route: GET /latest
#
# Uses the $default stage so the URL has no stage path prefix:
#   https://<api-id>.execute-api.<region>.amazonaws.com/latest
# ---------------------------------------------------------------------------
resource "aws_apigatewayv2_api" "main" {
  name          = "${var.project_name}-api"
  protocol_type = "HTTP"
  description   = "Latest weather reading from Redshift Spectrum"

  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET", "OPTIONS"]
    allow_headers = ["Content-Type"]
    max_age       = 300
  }
}

resource "aws_apigatewayv2_integration" "query" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.query.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "latest" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "GET /latest"
  target    = "integrations/${aws_apigatewayv2_integration.query.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "apigw_query" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.query.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}
