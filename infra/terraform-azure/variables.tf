variable "cluster_name" {
  description = "AKS cluster name."
  type        = string
  default     = "sentinel"
}

variable "resource_group_name" {
  description = "Azure resource group to create the cluster (and everything in it) under."
  type        = string
  default     = "sentinel-rg"
}

variable "location" {
  description = "Azure region for the cluster."
  type        = string
  default     = "eastus"
}

variable "node_vm_size" {
  description = "VM size for the single default node pool. AKS's control plane itself is free (unlike EKS); this is kept small to fit comfortably within a student/free-tier credit."
  type        = string
  default     = "Standard_B2s"
}
