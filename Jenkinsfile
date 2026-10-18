pipeline {
    agent any

    options {
        buildDiscarder(logRotator(numToKeepStr: '10'))
        disableConcurrentBuilds()
        timeout(time: 20, unit: 'MINUTES')
    }

    environment {
        PYTHONUNBUFFERED = '1'
        PIP_NO_CACHE_DIR = '1'
    }

    stages {
        stage('Checkout & Metadata') {
            steps {
                script {
                    // Sync from mounted local repository if workspace is not already populated by SCM
                    if (!fileExists('requirements.txt') && fileExists('/workspace/sentinel/requirements.txt')) {
                        echo "[CI] Workspace empty; syncing from /workspace/sentinel..."
                        sh "cp -R /workspace/sentinel/. ."
                    }

                    env.GIT_SHORT_SHA = sh(returnStdout: true, script: 'git rev-parse --short HEAD 2>/dev/null || echo "39ec313"').trim()
                    echo "=========================================================="
                    echo "SENTINEL CI Pipeline (Stage A - Local Build)"
                    echo "Repository: SENTINEL"
                    echo "Commit SHA: ${env.GIT_SHORT_SHA}"
                    echo "=========================================================="
                }
            }
        }

        stage('Code Quality (Black & Pylint)') {
            steps {
                sh '''
                    echo "[CI] Setting up Python virtual environment..."
                    python3 -m venv .venv
                    . .venv/bin/activate
                    pip install -r requirements.txt pytest-cov black pylint

                    echo "[CI] Running Black format check..."
                    python -m black --check services/

                    echo "[CI] Running Pylint static analysis..."
                    python -m pylint services/
                '''
            }
        }

        stage('Unit Tests & Coverage (Pytest)') {
            steps {
                sh '''
                    echo "[CI] Executing Pytest with >=80% coverage threshold..."
                    . .venv/bin/activate
                    python -m pytest tests -q --cov=services --cov-report=term-missing --cov-report=xml --cov-fail-under=80
                '''
            }
        }

        stage('Build Docker Images') {
            parallel {
                stage('Build: hello') {
                    steps {
                        echo "[CI] Building sentinel/hello:${env.GIT_SHORT_SHA}..."
                        sh "docker build -t sentinel/hello:${env.GIT_SHORT_SHA} services/hello"
                    }
                }
                stage('Build: demo-api') {
                    steps {
                        echo "[CI] Building sentinel/demo-api:${env.GIT_SHORT_SHA}..."
                        sh "docker build -t sentinel/demo-api:${env.GIT_SHORT_SHA} services/demo_api"
                    }
                }
                stage('Build: predictor') {
                    steps {
                        echo "[CI] Building sentinel/predictor:${env.GIT_SHORT_SHA}..."
                        sh "docker build -t sentinel/predictor:${env.GIT_SHORT_SHA} -f services/predictor/Dockerfile ."
                    }
                }
                stage('Build: diagnosis-agent') {
                    steps {
                        echo "[CI] Building sentinel/diagnosis-agent:${env.GIT_SHORT_SHA}..."
                        sh "docker build -t sentinel/diagnosis-agent:${env.GIT_SHORT_SHA} -f services/diagnosis_agent/Dockerfile ."
                    }
                }
                stage('Build: remediator') {
                    steps {
                        echo "[CI] Building sentinel/remediator:${env.GIT_SHORT_SHA}..."
                        sh "docker build -t sentinel/remediator:${env.GIT_SHORT_SHA} -f services/remediator/Dockerfile ."
                    }
                }
                stage('Build: api') {
                    steps {
                        echo "[CI] Building sentinel/api:${env.GIT_SHORT_SHA}..."
                        sh "docker build -t sentinel/api:${env.GIT_SHORT_SHA} -f services/api/Dockerfile ."
                    }
                }
            }
        }

        stage('Verify Built Images') {
            steps {
                script {
                    echo "=========================================================="
                    echo "Verifying local Docker images for commit ${env.GIT_SHORT_SHA}:"
                    sh """
                        docker images | grep -E "sentinel/(hello|demo-api|predictor|diagnosis-agent|remediator|api)" | grep "${env.GIT_SHORT_SHA}"
                    """
                    echo "=========================================================="
                }
            }
        }
    }

    post {
        always {
            deleteDir()
        }
        success {
            echo "SUCCESS: Stage A build and verification succeeded for ${env.GIT_SHORT_SHA}."
        }
        failure {
            echo "FAILURE: Pipeline failed. Check step logs above."
        }
    }
}
