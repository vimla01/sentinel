output "cluster_name" {
  value = module.eks.cluster_name
}

output "region" {
  value = var.aws_region
}

output "next_step" {
  description = "Commands that point kubectl at the new cluster and install ArgoCD."
  value       = "aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name} && bash scripts/bootstrap-argocd.sh ${module.eks.cluster_name} aws"
}
