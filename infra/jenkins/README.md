# SENTINEL Local Jenkins CI (Stage A)

This directory provides the local Jenkins configuration for building, testing, and packaging SENTINEL application services without cloud or AWS/EKS dependencies.

---

## 1. Confirmed Services & Docker Images

Stage A targets the **six internal application services** of SENTINEL:

| Service | Build Context | Dockerfile | Generated Image Tag |
| :--- | :--- | :--- | :--- |
| **hello** | `services/hello` | `services/hello/Dockerfile` | `sentinel/hello:<git-short-sha>` |
| **demo-api** | `services/demo_api` | `services/demo_api/Dockerfile` | `sentinel/demo-api:<git-short-sha>` |
| **predictor** | `.` (Repo Root) | `services/predictor/Dockerfile` | `sentinel/predictor:<git-short-sha>` |
| **diagnosis-agent** | `.` (Repo Root) | `services/diagnosis_agent/Dockerfile` | `sentinel/diagnosis-agent:<git-short-sha>` |
| **remediator** | `.` (Repo Root) | `services/remediator/Dockerfile` | `sentinel/remediator:<git-short-sha>` |
| **api** | `.` (Repo Root) | `services/api/Dockerfile` | `sentinel/api:<git-short-sha>` |

*(Note: Third-party infrastructure pods like Prometheus, Loki, Promtail, Grafana, and Ollama use upstream vendor images and are not built here).*

---

## 2. Docker-Socket Security Tradeoffs

The local Jenkins instance runs as a container using the **Docker-outside-of-Docker (DooD)** pattern by mounting the host daemon socket (`/var/run/docker.sock`):

### Why DooD is used:
- **Direct image availability**: Images built inside the Jenkins container are immediately present in the host's Docker daemon.
- **Zero nested virtualization**: Eliminates the overhead, nested storage driver issues, and `--privileged` flags required by Docker-in-Docker (DinD).

### Security Tradeoff & Mitigation:
1. **Root-Equivalent Host Access**:
   - Access to `/var/run/docker.sock` grants any process the ability to communicate with the host Docker daemon. A process with socket access can run arbitrary containers, mount host root directories (`-v /:/host`), or manipulate host network namespaces.
2. **Local Environment Safety**:
   - For **local developer environments**, DooD is the industry standard.
   - Jenkins is bound exclusively to `localhost:8080` and `50000`.
   - The container runs as non-root `jenkins` (UID 1000) and is granted access to the socket strictly via the host Docker group ID (`group_add` with GID `117`).
3. **Production Recommendations (Future)**:
   - In production or shared team infrastructure, run builds on isolated ephemeral agent nodes (e.g. Kubernetes agent pods using Kaniko or rootless BuildKit) where the host Docker daemon is never exposed to build jobs.

---

## 3. How to Run Jenkins Locally

### Start Jenkins:
```bash
./scripts/run_jenkins.sh start
```
This automatically detects your host Docker GID, builds the custom Jenkins runner image with Python 3 and Docker CLI, and launches the container in the background.

### Retrieve Initial Admin Password:
```bash
./scripts/run_jenkins.sh password
```

### Access Jenkins UI:
Navigate to [http://localhost:8080](http://localhost:8080) in your browser.

---

## 4. Configuring the Pipeline Job in Jenkins

1. On the Jenkins home screen, click **New Item**.
2. Enter the name: `sentinel-ci` and select **Pipeline**, then click **OK**.
3. Under the **Pipeline** configuration section:
   - **Definition**: Select `Pipeline script from SCM`.
   - **SCM**: Select `Git`.
   - **Repository URL**:
     - For local repository: `/workspace/sentinel` or the local Git directory, OR
     - GitHub URL: `https://github.com/vimla01/sentinel.git` (or your local remote).
   - **Branches to build**: `*/main`
   - **Script Path**: `Jenkinsfile`
4. Click **Save** and then click **Build Now**.

---

## 5. Pipeline Stages in `Jenkinsfile`

1. **Checkout & Metadata**: Extracts short Git commit SHA (`git rev-parse --short HEAD`).
2. **Code Quality**:
   - Creates a virtual environment.
   - Runs `python -m black --check services/`
   - Runs `python -m pylint services/`
3. **Unit Tests & Coverage**:
   - Runs `python -m pytest tests -q --cov=services --cov-report=term-missing --cov-report=xml --cov-fail-under=80`
4. **Build Docker Images**:
   - Builds all 6 internal images in parallel tagged with the Git short SHA (`:${GIT_SHORT_SHA}`).
5. **Verify Built Images**:
   - Runs `docker images` filtered to confirm all 6 images exist locally with the exact SHA tag.
