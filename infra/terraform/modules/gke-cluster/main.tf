# GKE Autopilot: Google manages node pools/sizing entirely, which keeps this
# module as small as the local-cluster one - no node pool, machine type, or
# autoscaling config to maintain. Uses the project's default VPC/subnet
# rather than creating custom networking, matching this project's existing
# scope (a demo-grade cluster, not hardened production networking).
resource "google_container_cluster" "gke" {
  name     = var.cluster_name
  project  = var.project_id
  location = var.region

  enable_autopilot = true
  network          = "default"

  # Matches the local-cluster module's `kind delete cluster` on destroy -
  # `terraform destroy` should actually tear the cluster down, not block on
  # GKE's deletion-protection default.
  deletion_protection = false
}
