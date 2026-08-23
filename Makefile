.DEFAULT_GOAL := help

CLUSTER_NAME ?= sentinel
ARGO_NAMESPACE ?= argocd

.PHONY: help init plan apply destroy bootstrap test lint build
help:
	@echo "make init|plan|apply|destroy|bootstrap|test|lint|build"

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
	python -m pytest tests -q

lint:
	python -m compileall -q services tests

build:
	docker build -t sentinel/hello:dev services/hello
