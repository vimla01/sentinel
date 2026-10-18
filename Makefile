.DEFAULT_GOAL := help

CLUSTER_NAME ?= sentinel
ARGO_NAMESPACE ?= argocd

.PHONY: help init plan apply destroy bootstrap test lint build load
help:
	@echo "make init|plan|apply|destroy|bootstrap|test|lint|build|load"

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
