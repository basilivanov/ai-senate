import os
import subprocess
import re
from typing import List, Optional

from pydantic import BaseModel


class GitDiffResult(BaseModel):
    project_path: str
    diff_type: str
    diff_content: str
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0
    truncated: bool = False
    file_list: List[str] = []


ALLOWED_ROOTS_ENV = "AI_SENATE_PROJECT_ROOTS"
DEFAULT_ALLOWED_ROOTS = "/opt/solarsage-astro,/opt/solarsage,/tmp/grace-orchestrator-export"


def _get_allowed_roots() -> List[str]:
    env_val = os.environ.get(ALLOWED_ROOTS_ENV, "").strip()
    if env_val:
        return [r.strip() for r in env_val.split(",") if r.strip()]
    return [r.strip() for r in DEFAULT_ALLOWED_ROOTS.split(",") if r.strip()]


def validate_project_path(project_path: str) -> bool:
    allowed = _get_allowed_roots()
    real = os.path.realpath(project_path)
    return any(real.startswith(root) for root in allowed)


def _build_diff_command(project_path: str, diff_type: str) -> List[str]:
    if diff_type == "unstaged":
        return ["git", "-C", project_path, "diff"]
    elif diff_type == "staged":
        return ["git", "-C", project_path, "diff", "--cached"]
    elif diff_type == "head~1":
        return ["git", "-C", project_path, "diff", "HEAD~1..HEAD"]
    elif diff_type.startswith("head~"):
        n = diff_type[len("head~"):]
        return ["git", "-C", project_path, "diff", f"HEAD~{n}..HEAD"]
    elif diff_type.startswith("last:"):
        n = diff_type[len("last:"):]
        return ["git", "-C", project_path, "diff", f"HEAD~{n}..HEAD"]
    elif diff_type.startswith("branch:"):
        spec = diff_type[len("branch:"):]
        if ".." in spec:
            base, head = spec.split("..", 1)
            return ["git", "-C", project_path, "diff", f"{base}..{head}"]
        return ["git", "-C", project_path, "diff", spec]
    else:
        return ["git", "-C", project_path, "diff", "HEAD~1..HEAD"]


def _parse_diff_stat(diff_content: str) -> tuple:
    files_changed = 0
    insertions = 0
    deletions = 0
    file_list: List[str] = []
    current_file = None

    for line in diff_content.splitlines():
        if line.startswith("diff --git "):
            match = re.match(r'diff --git a/(.+?) b/', line)
            if match:
                current_file = match.group(1)
                file_list.append(current_file)
                files_changed += 1
        elif line.startswith("+") and not line.startswith("+++"):
            insertions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1

    return files_changed, insertions, deletions, file_list


def get_git_diff(
    project_path: str,
    diff_type: str = "head~1",
    max_lines: int = 2000,
) -> GitDiffResult:
    if not validate_project_path(project_path):
        raise ValueError(f"Project path not in allowed roots: {project_path}")

    real = os.path.realpath(project_path)
    if not os.path.isdir(os.path.join(real, ".git")):
        raise ValueError(f"Not a git repository: {real}")

    cmd = _build_diff_command(real, diff_type)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            cwd=real, env={**os.environ, "GIT_DIR": os.path.join(real, ".git")},
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "not a git repository" in stderr.lower():
                raise ValueError(f"Not a git repository: {real}")
            if "unknown revision" in stderr.lower() or "bad revision" in stderr.lower():
                return GitDiffResult(
                    project_path=real, diff_type=diff_type,
                    diff_content="", files_changed=0, insertions=0, deletions=0,
                    truncated=False, file_list=[],
                )
            diff_content = ""
        else:
            diff_content = result.stdout
    except subprocess.TimeoutExpired:
        return GitDiffResult(
            project_path=real, diff_type=diff_type,
            diff_content="[Error: git diff timed out after 30s]",
            files_changed=0, insertions=0, deletions=0, truncated=True, file_list=[],
        )

    truncated = len(diff_content.splitlines()) > max_lines
    if truncated:
        lines = diff_content.splitlines()[:max_lines]
        diff_content = "\n".join(lines) + f"\n... (truncated at {max_lines} lines)"

    files_changed, insertions, deletions, file_list = _parse_diff_stat(diff_content)

    return GitDiffResult(
        project_path=real,
        diff_type=diff_type,
        diff_content=diff_content,
        files_changed=files_changed,
        insertions=insertions,
        deletions=deletions,
        truncated=truncated,
        file_list=file_list[:100],
    )