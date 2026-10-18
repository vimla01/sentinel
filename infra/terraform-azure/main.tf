# A resource group holds everything this creates, so `terraform destroy`
# cleanly tears down the whole thing in one step - matching the local
# Kind module's `kind delete cluster` and the GKE module's clean teardown.
resource "azurerm_resource_group" "sentinel" {
  name     = var.resource_group_name
  location = var.location
}

# AKS has no Autopilot-equivalent fully-managed-nodes mode the way GKE
# does - the control plane itself is free, but the node pool's VMs are
# real, billed compute. This uses the smallest practical single-node pool
# rather than trying to match GKE Autopilot's zero-node-config model, to
# stay well within a student credit.
resource "azurerm_kubernetes_cluster" "sentinel" {
  name                = var.cluster_name
  location            = azurerm_resource_group.sentinel.location
  resource_group_name = azurerm_resource_group.sentinel.name
  dns_prefix          = var.cluster_name

  default_node_pool {
    name       = "default"
    node_count = 1
    vm_size    = var.node_vm_size
  }

  identity {
    type = "SystemAssigned"
  }
}
