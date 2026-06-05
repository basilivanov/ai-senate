import os
import fnmatch
import subprocess
from pathlib import Path
from typing import List, Optional, Set

from app.council_core.contracts import DocumentRef, ProjectContext

DEFAULT_FILE_PATTERNS = [
    "**/*.py", "**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx",
    "**/*.yaml", "**/*.yml", "**/*.json", "**/*.toml",
    "**/*.md", "**/*.go", "**/*.rs", "**/*.sql",
]

DEFAULT_EXCLUDE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".nuxt", "target", "vendor",
    ".idea", ".vscode", "coverage", ".cache", ".tox",
    "e2e-screenshots", "test-results", "playwright-report",
}

DEFAULT_EXCLUDE_FILES = {
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "go.sum", ".DS_Store", "tsconfig.tsbuildinfo",
    "*.pyc", "*.pyo", "*.so", "*.dll", "*.dylib",
}

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


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


def _build_tree(project_path: str, max_depth: int = 4, max_entries: int = 200) -> str:
    lines: List[str] = []
    count = 0

    for root, dirs, files in os.walk(project_path):
        depth = root.replace(project_path, "").count(os.sep)
        if depth >= max_depth:
            dirs.clear()
            continue

        dirs[:] = sorted(d for d in dirs if d not in DEFAULT_EXCLUDE_DIRS)

        rel_root = os.path.relpath(root, project_path)
        if rel_root == ".":
            rel_root = ""
        prefix = "  " * depth

        for f in sorted(files):
            if f in DEFAULT_EXCLUDE_FILES:
                continue
            if any(fnmatch.fnmatch(f, pat) for pat in ("*.pyc", "*.pyo", "*.so", "*.dll", "*.dylib", "*.tsbuildinfo")):
                continue
            rel = os.path.join(rel_root, f) if rel_root else f
            lines.append(f"{prefix}{f}")
            count += 1
            if count >= max_entries:
                lines.append(f"{prefix}... (truncated, {max_entries} entries max)")
                return "\n".join(lines)

    return "\n".join(lines)


def _collect_files(
    project_path: str,
    file_patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None,
    max_file_size_kb: int = 50,
    max_total_tokens: int = 15000,
    priority_files: Optional[Set[str]] = None,
    max_scan_files: int = 5000,
) -> List[DocumentRef]:
    patterns = file_patterns or DEFAULT_FILE_PATTERNS
    excludes = exclude_patterns or []
    max_bytes = max_file_size_kb * 1024
    collected: List[DocumentRef] = []
    total_tokens = 0
    priority = priority_files or set()
    scanned = 0

    priority_items: List[tuple] = []
    regular_items: List[tuple] = []

    for root, dirs, files in os.walk(project_path):
        dirs[:] = sorted(d for d in dirs if d not in DEFAULT_EXCLUDE_DIRS)

        for f in sorted(files):
            if f in DEFAULT_EXCLUDE_FILES:
                continue
            if scanned >= max_scan_files:
                break
            scanned += 1
            full = os.path.join(root, f)
            rel = os.path.relpath(full, project_path)

            if not any(fnmatch.fnmatch(rel, pat) for pat in patterns):
                continue

            if excludes and any(fnmatch.fnmatch(rel, pat) for pat in excludes):
                continue

            try:
                sz = os.path.getsize(full)
            except OSError:
                continue

            if sz > max_bytes:
                continue

            if total_tokens >= max_total_tokens:
                break

            is_priority = rel in priority
            depth = rel.count(os.sep)
            entry = (is_priority, -depth, rel, full)

            if is_priority:
                priority_items.append(entry)
            else:
                regular_items.append(entry)

    all_items = sorted(priority_items, key=lambda x: (-x[0], x[1])) + sorted(regular_items, key=lambda x: (x[1], x[2]))

    for _, _, rel, full in all_items:
        if total_tokens >= max_total_tokens:
            break

        try:
            with open(full, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            continue

        tokens = _estimate_tokens(content)
        if total_tokens + tokens > max_total_tokens:
            remaining = (max_total_tokens - total_tokens) * 4
            if remaining < 200:
                break
            content = content[:remaining] + "\n... (truncated)"
            tokens = _estimate_tokens(content)

        total_tokens += tokens
        role = ""
        fname = os.path.basename(rel)
        if "test" in fname.lower() or "spec" in fname.lower():
            role = "test"
        elif fname.startswith("README") or fname.startswith("CHANGELOG"):
            role = "docs"
        elif fname in ("package.json", "pyproject.toml", "go.mod", "Makefile", "Dockerfile"):
            role = "config"

        collected.append(DocumentRef(filename=rel, role=role, content=content))

    return collected


def build_project_digest(
    project_path: str,
    file_patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None,
    max_file_size_kb: int = 50,
    max_total_tokens: int = 15000,
    respect_gitignore: bool = True,
    priority_files: Optional[Set[str]] = None,
) -> ProjectContext:
    if not validate_project_path(project_path):
        raise ValueError(f"Project path not in allowed roots: {project_path}")

    real = os.path.realpath(project_path)
    if not os.path.isdir(real):
        raise ValueError(f"Not a directory: {real}")

    if respect_gitignore:
        try:
            result = subprocess.run(
                ["git", "-C", real, "ls-files", "--others", "--ignored", "--exclude-standard"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                gitignored = [l for l in result.stdout.strip().splitlines()[:500]]
                if not exclude_patterns:
                    exclude_patterns = []
                exclude_patterns.extend(gitignored)
        except (subprocess.TimeoutExpired, OSError):
            pass

    tree = _build_tree(real)
    files = _collect_files(
        real, file_patterns, exclude_patterns, max_file_size_kb, max_total_tokens, priority_files,
    )
    total_tokens = sum(_estimate_tokens(f.content) for f in files)
    truncated = total_tokens >= max_total_tokens

    return ProjectContext(
        path=real,
        tree=tree,
        files=files,
        total_tokens_estimate=total_tokens,
        truncated=truncated,
    )