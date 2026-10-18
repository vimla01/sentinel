output "cluster_name" {
  value = google_container_cluster.gke.name
}

output "region" {
  value = var.region
}

output "project_id" {
  value = var.project_id
}

output "get_credentials_command" {
  description = "Run this to point kubectl/gcloud at the new cluster."
  value       = "gcloud container clusters get-credentials ${google_container_cluster.gke.name} --region ${var.region} --project ${var.project_id}"
}
