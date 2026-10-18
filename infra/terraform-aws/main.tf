# EKS needs supporting infrastructure none of the other two clouds required
# (GKE Autopilot and AKS each need just one resource): a VPC with subnets
# across multiple AZs, plus IAM roles for the control plane and node group.
# Using the community terraform-aws-modules/{vpc,eks} modules rather than
# hand-rolling this - they're the de facto standard for EKS on Terraform
# (referenced in AWS's and HashiCorp's own EKS docs) and dramatically
# reduce the surface for misconfiguration on infrastructure this complex,
# especially with no live AWS account to iterate against while writing it.

data "aws_availability_zones" "available" {
  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, 2)
}

# No NAT gateway (~$32/month fixed cost on its own) - worker nodes sit in
# public subnets with public IPs instead, a standard cost-saving tradeoff
# for a short-lived demo cluster that gets destroyed right after use, not
# something to carry into a real production setup.
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "${var.cluster_name}-vpc"
  cidr = "10.0.0.0/16"

  azs                     = local.azs
  public_subnets          = ["10.0.1.0/24", "10.0.2.0/24"]
  map_public_ip_on_launch = true
  enable_nat_gateway      = false

  public_subnet_tags = {
    "kubernetes.io/role/elb" = "1"
  }
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.cluster_name
  cluster_version = "1.31"

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.public_subnets

  cluster_endpoint_public_access = true

  eks_managed_node_groups = {
    default = {
      instance_types = [var.node_instance_type]
      min_size       = 1
      max_size       = 1
      desired_size   = 1
      subnet_ids     = module.vpc.public_subnets
    }
  }
}
