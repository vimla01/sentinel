# Separate Terraform root from infra/terraform/ (the local Kind setup)
# deliberately, not a toggle inside it: the google provider authenticates
# eagerly at plan/apply time even for a module instance with count = 0,
# which would require every local-dev `terraform plan` to have GCP
# credentials configured just to provision a local Kind cluster. Keeping
# this a fully separate root means the local workflow in infra/terraform/
# is completely unaffected by any of this.
module "gke_cluster" {
  source = "../terraform/modules/gke-cluster"

  cluster_name = var.cluster_name
  project_id   = var.gcp_project_id
  region       = var.gcp_region
}
