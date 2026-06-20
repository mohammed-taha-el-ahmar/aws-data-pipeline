terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # ── Remote state backend (optional but recommended for shared / repeat use) ──
  #
  # Step 1 — create the bucket + DynamoDB table ONCE (from project root):
  #   source .env
  #   ./scripts/bootstrap-tf-backend.sh
  #
  # Step 2 — uncomment this block (the script prints the exact values to use):
  #
  # backend "s3" {
  #   bucket         = "<project>-tfstate-<account-id>"   # printed by bootstrap script
  #   key            = "data-pipeline/terraform.tfstate"
  #   region         = "eu-west-3"
  #   dynamodb_table = "<project>-tf-locks"
  #   encrypt        = true
  # }
  #
  # Step 3 — re-initialise (Terraform will offer to migrate local state → S3):
  #   terraform init
  #
  # For a solo demo you can leave this commented out — local state is fine as
  # long as you don't lose the .tfstate file before running terraform destroy.
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}
