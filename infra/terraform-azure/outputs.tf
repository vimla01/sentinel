output "cluster_name" {
  value = azurerm_kubernetes_cluster.sentinel.name
}

output "resource_group_name" {
  value = azurerm_resource_group.sentinel.name
}

output "next_step" {
  description = "Commands that point kubectl at the new cluster and install ArgoCD."
  value       = "az aks get-credentials --resource-group ${azurerm_resource_group.sentinel.name} --name ${azurerm_kubernetes_cluster.sentinel.name} --overwrite-existing && bash scripts/bootstrap-argocd.sh ${azurerm_kubernetes_cluster.sentinel.name} azure"
}
