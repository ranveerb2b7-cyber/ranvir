terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.72"
    }
  }
  # State in S3 with locking; bucket/key come from environments/<env>.backend.hcl:
  #   terraform init -backend-config=environments/staging.backend.hcl
  backend "s3" {}
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project     = "sellerscope"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
