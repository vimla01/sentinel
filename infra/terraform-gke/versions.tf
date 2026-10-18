terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

# Authenticates via `gcloud auth application-default login` - the standard
# local-dev flow. No service account key is committed anywhere.
provider "google" {
  project = var.gcp_project_id
  region  = var.gcp_region
}
