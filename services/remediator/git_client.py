import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger("remediator.git")


class GitClient:
    """Manages Git-native operations for GitOps remediation.
    Commits state changes (rollback/scale) to the Git repository so that
    ArgoCD reconciles the desired state from Git, preventing automated
    selfHeal from reverting out-of-band cluster modifications."""

    def __init__(self, repo_path: str = ".") -> None:
        self.repo_path = Path(repo_path).resolve()

    def is_git_repo(self) -> bool:
        try:
            res = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.repo_path),
                    "rev-parse",
                    "--is-inside-work-tree",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            return res.returncode == 0 and res.stdout.strip() == "true"
        except Exception as exc:
            logger.debug("is_git_repo check failed: %s", exc)
            return False

    def rollback_deployment(
        self,
        deployment_name: str,
        target_revision: str,
        app_path: str = "infra/k8s/apps",
    ) -> str:
        """Restores deployment manifests to target_revision and commits to Git."""
        if not self.is_git_repo():
            raise RuntimeError(f"{self.repo_path} is not a valid git repository")

        rel_path = f"{app_path}/{deployment_name}"
        logger.info(
            "reverting %s to revision %s in %s",
            rel_path,
            target_revision,
            self.repo_path,
        )

        checkout = subprocess.run(
            [
                "git",
                "-C",
                str(self.repo_path),
                "checkout",
                target_revision,
                "--",
                rel_path,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if checkout.returncode != 0:
            raise RuntimeError(f"git checkout failed: {checkout.stderr.strip()}")

        subprocess.run(
            ["git", "-C", str(self.repo_path), "add", rel_path],
            capture_output=True,
            text=True,
            check=False,
        )

        commit_msg = (
            f"remediate(gitops): rollback {deployment_name} to {target_revision}\n\n"
            f"Automated Git-native rollback by SENTINEL remediator."
        )
        commit = subprocess.run(
            [
                "git",
                "-C",
                str(self.repo_path),
                "-c",
                "user.name=sentinel-remediator",
                "-c",
                "user.email=sentinel@system.local",
                "commit",
                "-m",
                commit_msg,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if commit.returncode != 0:
            output = commit.stdout + commit.stderr
            if "nothing to commit" in output:
                logger.info("working tree already matches revision %s", target_revision)
                return target_revision
            raise RuntimeError(f"git commit failed: {commit.stderr.strip()}")

        rev_parse = subprocess.run(
            ["git", "-C", str(self.repo_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        return rev_parse.stdout.strip()

    def scale_deployment(
        self,
        deployment_name: str,
        replicas: int,
        app_path: str = "infra/k8s/apps",
    ) -> str:
        """Updates replica count in deployment.yaml and commits to Git."""
        if not self.is_git_repo():
            raise RuntimeError(f"{self.repo_path} is not a valid git repository")

        deploy_yaml = self.repo_path / app_path / deployment_name / "deployment.yaml"
        if not deploy_yaml.exists():
            raise FileNotFoundError(f"{deploy_yaml} does not exist")

        content = deploy_yaml.read_text(encoding="utf-8")
        new_content = re.sub(
            r"replicas:\s*\d+", f"replicas: {replicas}", content, count=1
        )
        if new_content == content:
            return "no change"
        deploy_yaml.write_text(new_content, encoding="utf-8")

        rel_path = f"{app_path}/{deployment_name}/deployment.yaml"
        subprocess.run(
            ["git", "-C", str(self.repo_path), "add", rel_path],
            capture_output=True,
            text=True,
            check=False,
        )

        commit_msg = (
            f"remediate(gitops): scale {deployment_name} to {replicas} replicas"
        )
        commit = subprocess.run(
            [
                "git",
                "-C",
                str(self.repo_path),
                "-c",
                "user.name=sentinel-remediator",
                "-c",
                "user.email=sentinel@system.local",
                "commit",
                "-m",
                commit_msg,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if commit.returncode != 0:
            output = commit.stdout + commit.stderr
            if "nothing to commit" in output:
                return "no change"
            raise RuntimeError(f"git commit failed: {commit.stderr.strip()}")

        rev_parse = subprocess.run(
            ["git", "-C", str(self.repo_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        return rev_parse.stdout.strip()
