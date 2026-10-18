terraform {
  required_version = ">= 1.6.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

# Authenticates via `az login` (Azure CLI) - the standard local-dev flow,
# relying on the CLI's active subscription context, same pattern as the GKE
# root (infra/terraform-gke/) relying on `gcloud auth application-default
# login`. A separate Terraform root from local Kind and from the GKE root,
# for the same reason GKE got its own: a cloud provider that authenticates
# eagerly shouldn't be able to break `terraform plan` for anyone just
# running the local Kind setup.
provider "azurerm" {
  features {}
}
