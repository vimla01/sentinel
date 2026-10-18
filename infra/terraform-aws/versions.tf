terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# Authenticates via the AWS CLI's default credential chain (`aws configure`,
# or AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY env vars) - a separate
# Terraform root from local Kind, GKE, and AKS, for the same reason all
# three already are: the provider authenticates eagerly even when unused,
# which would otherwise force every local `terraform plan` to need AWS
# credentials it has no reason to need.
provider "aws" {
  region = var.aws_region
}
