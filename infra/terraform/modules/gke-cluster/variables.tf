variable "cluster_name" {
  type        = string
  description = "GKE cluster name."
}

variable "project_id" {
  type        = string
  description = "GCP project ID to create the cluster in."
}

variable "region" {
  type        = string
  description = "GCP region for the Autopilot cluster."
  default     = "us-central1"
}
