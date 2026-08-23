variable "cluster_name" {
  type        = string
  description = "Kind cluster name."
}

variable "kubeconfig" {
  type        = string
  description = "Optional kubeconfig path."
  default     = ""
}
