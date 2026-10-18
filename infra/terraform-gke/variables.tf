variable "gcp_project_id" {
  description = "GCP project ID to create the cluster in. Required - no default on purpose."
  type        = string
}

variable "gcp_region" {
  description = "GCP region for the Autopilot cluster."
  type        = string
  default     = "us-central1"
}

variable "cluster_name" {
  description = "GKE cluster name."
  type        = string
  default     = "sentinel"
}
