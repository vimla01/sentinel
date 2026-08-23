variable "cluster_name" {
  description = "Name of the local Kind cluster."
  type        = string
  default     = "sentinel"
}

variable "kubeconfig" {
  description = "Optional kubeconfig path passed to Kind and kubectl."
  type        = string
  default     = ""
}
