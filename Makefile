.DEFAULT_GOAL := help

CLUSTER_NAME ?= sentinel
ARGO_NAMESPACE ?= argocd
GCP_PROJECT_ID ?=
GCP_REGION ?= us-central1
AZURE_RESOURCE_GROUP ?= sentinel-rg
AZURE_LOCATION ?= eastus
AWS_REGION ?= us-east-1
NODE_INSTANCE_TYPE ?= t3.small

.PHONY: help init plan apply destroy bootstrap test lint build load gke-apply gke-bootstrap gke-destroy azure-apply azure-bootstrap azure-destroy aws-apply aws-bootstrap aws-destroy
help:
	@echo "make init|plan|apply|destroy|bootstrap|test|lint|build|load"
	@echo "make gke-apply GCP_PROJECT_ID=<id> | gke-bootstrap | gke-destroy GCP_PROJECT_ID=<id>"
	@echo "make azure-apply | azure-bootstrap | azure-destroy"
	@echo "make aws-apply | aws-bootstrap | aws-destroy"

init:
	terraform -chdir=infra/terraform init

plan: init
	terraform -chdir=infra/terraform plan -var="cluster_name=$(CLUSTER_NAME)"

apply: init
	terraform -chdir=infra/terraform apply -var="cluster_name=$(CLUSTER_NAME)"

bootstrap:
	bash scripts/bootstrap-argocd.sh $(CLUSTER_NAME)

destroy:
	terraform -chdir=infra/terraform destroy -var="cluster_name=$(CLUSTER_NAME)"

test:
	python -m pytest tests -q --cov=services --cov-report=term-missing --cov-report=xml --cov-fail-under=80

lint:
	python -m black --check services/
	python -m pylint services/

test-integration:
	python -m pytest tests/test_integration_e2e.py -v

test-load:
	python scripts/load_test_diagnosis.py

build:
	docker build -t sentinel/hello:dev services/hello
	docker build -t sentinel/demo-api:dev services/demo_api
	docker build -t sentinel/predictor:dev -f services/predictor/Dockerfile .
	docker build -t sentinel/diagnosis-agent:dev -f services/diagnosis_agent/Dockerfile .
	docker build -t sentinel/remediator:dev -f services/remediator/Dockerfile .
	docker build -t sentinel/api:dev -f services/api/Dockerfile .

load: build
	kind load docker-image sentinel/hello:dev --name $(CLUSTER_NAME)
	kind load docker-image sentinel/demo-api:dev --name $(CLUSTER_NAME)
	kind load docker-image sentinel/predictor:dev --name $(CLUSTER_NAME)
	kind load docker-image sentinel/diagnosis-agent:dev --name $(CLUSTER_NAME)
	kind load docker-image sentinel/remediator:dev --name $(CLUSTER_NAME)
	kind load docker-image sentinel/api:dev --name $(CLUSTER_NAME)

# GKE Autopilot - separate Terraform root (infra/terraform-gke), see
# docs/DEPLOYMENT.md#deploying-to-gke. Requires `gcloud auth
# application-default login` once, and real images in a registry (kind
# load does not exist on GKE) - see scripts/promote-image.sh.
gke-apply:
	terraform -chdir=infra/terraform-gke init
	terraform -chdir=infra/terraform-gke apply \
		-var="gcp_project_id=$(GCP_PROJECT_ID)" \
		-var="gcp_region=$(GCP_REGION)" \
		-var="cluster_name=$(CLUSTER_NAME)"

gke-bootstrap:
	eval "$$(terraform -chdir=infra/terraform-gke output -raw next_step)"

gke-destroy:
	terraform -chdir=infra/terraform-gke destroy \
		-var="gcp_project_id=$(GCP_PROJECT_ID)" \
		-var="gcp_region=$(GCP_REGION)" \
		-var="cluster_name=$(CLUSTER_NAME)"

# AKS - separate Terraform root (infra/terraform-azure), see
# docs/DEPLOYMENT.md#deploying-to-aks. Requires `az login` once, and real
# images in a registry (kind load does not exist on AKS either) - see
# scripts/promote-image.sh.
azure-apply:
	terraform -chdir=infra/terraform-azure init
	terraform -chdir=infra/terraform-azure apply \
		-var="resource_group_name=$(AZURE_RESOURCE_GROUP)" \
		-var="location=$(AZURE_LOCATION)" \
		-var="cluster_name=$(CLUSTER_NAME)"

azure-bootstrap:
	eval "$$(terraform -chdir=infra/terraform-azure output -raw next_step)"

azure-destroy:
	terraform -chdir=infra/terraform-azure destroy \
		-var="resource_group_name=$(AZURE_RESOURCE_GROUP)" \
		-var="location=$(AZURE_LOCATION)" \
		-var="cluster_name=$(CLUSTER_NAME)"

# EKS - separate Terraform root (infra/terraform-aws), see
# docs/DEPLOYMENT.md#deploying-to-eks. Requires `aws configure` once, and
# real images in a registry (kind load does not exist on EKS either) - see
# scripts/promote-image.sh. Unlike GKE/AKS, the EKS control plane itself is
# billed (~$0.10/hr) even with zero nodes - destroy promptly after use.
aws-apply:
	terraform -chdir=infra/terraform-aws init
	terraform -chdir=infra/terraform-aws apply \
		-var="aws_region=$(AWS_REGION)" \
		-var="cluster_name=$(CLUSTER_NAME)" \
		-var="node_instance_type=$(NODE_INSTANCE_TYPE)"

aws-bootstrap:
	eval "$$(terraform -chdir=infra/terraform-aws output -raw next_step)"

aws-destroy:
	terraform -chdir=infra/terraform-aws destroy \
		-var="aws_region=$(AWS_REGION)" \
		-var="cluster_name=$(CLUSTER_NAME)" \
		-var="node_instance_type=$(NODE_INSTANCE_TYPE)"
