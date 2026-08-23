module "local_cluster" {
  source = "./modules/local-cluster"

  cluster_name = var.cluster_name
  kubeconfig   = var.kubeconfig
}
