variable "aws_region" {
  description = "AWS region for the cluster."
  type        = string
  default     = "us-east-1"
}

variable "cluster_name" {
  description = "EKS cluster name."
  type        = string
  default     = "sentinel"
}

variable "node_instance_type" {
  description = "EC2 instance type for the single worker node - kept small to stretch a limited credit."
  type        = string
  default     = "t3.small"
}
