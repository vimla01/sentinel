output "cluster_name" {
  value = module.gke_cluster.cluster_name
}

output "next_step" {
  description = "Commands that point kubectl at the new cluster and install ArgoCD."
  value       = "${module.gke_cluster.get_credentials_command} && bash scripts/bootstrap-argocd.sh ${module.gke_cluster.cluster_name} gke"
}
