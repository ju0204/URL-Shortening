terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}


module "dynamodb" {
  source             = "./modules/dynamodb"
  project_name       = var.project_name
  urls_ttl_attribute = "expiresAt"
}

module "iam" {
  source       = "./modules/iam"
  project_name = var.project_name

  urls_table_arn     = module.dynamodb.urls_table_arn
  clicks_table_arn   = module.dynamodb.clicks_table_arn
  insights_table_arn = module.dynamodb.insights_table_arn
}
