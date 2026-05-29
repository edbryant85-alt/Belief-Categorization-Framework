from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from belief_dashboard_agentflows.policies import CommandRisk


class GitAction(str, Enum):
    NONE = "none"
    LOCAL_COMMIT = "local_commit"
    PUSH_BRANCH = "push_branch"
    OPEN_PR = "open_pr"


@dataclass(frozen=True)
class GitPolicy:
    action: GitAction
    requires_human_confirmation: bool
    allowed_paths: tuple[str, ...]


GIT_POLICY_BY_RISK: dict[CommandRisk, GitPolicy] = {
    CommandRisk.READ_ONLY: GitPolicy(
        GitAction.LOCAL_COMMIT,
        False,
        ("belief-dashboard-tool/reports/", "belief-dashboard-tool/data/manual_imports/"),
    ),
    CommandRisk.INTERMEDIATE_WRITE: GitPolicy(
        GitAction.LOCAL_COMMIT,
        False,
        ("belief-dashboard-tool/reports/", "belief-dashboard-tool/data/manual_imports/"),
    ),
    CommandRisk.GUARDED_WRITE: GitPolicy(
        GitAction.LOCAL_COMMIT,
        True,
        (
            "belief-dashboard-tool/reports/",
            "belief-dashboard-tool/data/manual_imports/",
            "belief-dashboard-tool/data/queues/",
            "belief-dashboard-tool/data/outputs/",
        ),
    ),
    CommandRisk.PROMOTION: GitPolicy(GitAction.NONE, True, ()),
}


def git_status_porcelain(repo_dir: str | Path = ".") -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_dir,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Unable to read git status.")
    return [line for line in result.stdout.splitlines() if line.strip()]


def current_branch(repo_dir: str | Path = ".") -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo_dir,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Unable to read git branch.")
    return result.stdout.strip()


def assert_clean_worktree_at_start(repo_dir: str | Path = ".") -> None:
    dirty = git_status_porcelain(repo_dir)
    if dirty:
        raise PermissionError("Auto-git actions require a clean working tree at flow start.")


def assert_not_main_branch(repo_dir: str | Path = ".") -> None:
    branch = current_branch(repo_dir)
    if branch in {"main", "master"}:
        raise PermissionError("Auto-git actions require a dedicated agent branch, not main/master.")


def assert_paths_allowed(changed_paths: list[str], allowed_paths: tuple[str, ...]) -> None:
    forbidden = [
        path
        for path in changed_paths
        if not any(path.startswith(prefix) for prefix in allowed_paths)
    ]
    if forbidden:
        raise PermissionError(f"Changed paths are not allowed for this git policy: {', '.join(forbidden)}")


def changed_paths_from_porcelain(lines: list[str]) -> list[str]:
    paths: list[str] = []
    for line in lines:
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            paths.append(path)
    return paths


def assert_push_allowed(*, human_confirmed: bool, branch: str) -> None:
    if not human_confirmed:
        raise PermissionError("Pushing requires explicit human confirmation.")
    if branch in {"main", "master"}:
        raise PermissionError("Pushing to main/master is forbidden for agentflows.")
