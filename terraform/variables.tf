variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "eu-west-3"
}

variable "project_name" {
  description = "Prefix used when naming resources"
  type        = string
  default     = "data-pipeline"
}

variable "redshift_admin_username" {
  type    = string
  default = "admin"
}

variable "redshift_admin_password" {
  description = "Set via terraform.tfvars (gitignored) or TF_VAR_redshift_admin_password"
  type        = string
  sensitive   = true
}
