output "cluster_name" {
  description = "The local cluster name."
  value       = module.local_cluster.cluster_name
}

output "next_step" {
  description = "Command that installs ArgoCD and registers GitOps."
  value       = "bash scripts/bootstrap-argocd.sh ${module.local_cluster.cluster_name}"
}
