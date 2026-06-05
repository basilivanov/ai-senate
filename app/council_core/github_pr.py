import json
import logging
import re
import subprocess
from typing import Optional, Tuple

from app.council_core.contracts import PRContext, GitDiffContext, DocumentRef

log = logging.getLogger("ai_senate.github_pr")

_GH_PR_URL_RE = re.compile(
    r"https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)/?"
)


def parse_pr_url(url: str) -> Optional[Tuple[str, str, int]]:
    m = _GH_PR_URL_RE.match(url.strip())
    if not m:
        return None
    return m.group(1), m.group(2), int(m.group(3))


def fetch_pr_context(pr_url: str) -> PRContext:
    parsed = parse_pr_url(pr_url)
    if not parsed:
        raise ValueError(f"Invalid GitHub PR URL: {pr_url}")

    owner, repo, number = parsed

    result = subprocess.run(
        ["gh", "pr", "view", str(number), "--repo", f"{owner}/{repo}",
         "--json", "title,body,headRefName,baseRefName,author,state,url"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise ValueError(f"gh pr view failed: {result.stderr[:300]}")

    data = json.loads(result.stdout)

    return PRContext(
        url=pr_url,
        owner=owner,
        repo=repo,
        number=number,
        title=data.get("title", ""),
        body=data.get("body", "") or "",
        head_branch=data.get("headRefName", ""),
        base_branch=data.get("baseRefName", ""),
        author=data.get("author", {}).get("login", "") if isinstance(data.get("author"), dict) else str(data.get("author", "")),
        state=data.get("state", ""),
    )


def fetch_pr_diff(pr_url: str, max_lines: int = 2000) -> GitDiffContext:
    parsed = parse_pr_url(pr_url)
    if not parsed:
        raise ValueError(f"Invalid GitHub PR URL: {pr_url}")

    owner, repo, number = parsed

    result = subprocess.run(
        ["gh", "pr", "diff", str(number), "--repo", f"{owner}/{repo}"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise ValueError(f"gh pr diff failed: {result.stderr[:300]}")

    diff = result.stdout
    truncated = len(diff.splitlines()) > max_lines
    if truncated:
        lines = diff.splitlines()[:max_lines]
        diff = "\n".join(lines)

    files_changed = 0
    insertions = 0
    deletions = 0
    file_list = []
    for line in diff.splitlines():
        if line.startswith("diff --git"):
            files_changed += 1
            parts = line.split(" b/", 1)
            fname = parts[-1] if parts else line
            file_list.append(fname)
        elif line.startswith("+") and not line.startswith("+++"):
            insertions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1

    return GitDiffContext(
        diff_content=diff,
        diff_type=f"pr/{number}",
        files_changed=files_changed,
        insertions=insertions,
        deletions=deletions,
        truncated=truncated,
        file_list=file_list,
    )


def pr_to_documents(pr: PRContext) -> list:
    parts = [f"# {pr.title}"]
    if pr.body:
        parts.append(pr.body)
    content = "\n\n".join(parts) if any(parts) else pr.title

    return [DocumentRef(
        filename=f"pr-{pr.number}-description.md",
        role="pr_description",
        content=content,
    )]


def post_pr_comment(pr_url: str, comment: str) -> str:
    parsed = parse_pr_url(pr_url)
    if not parsed:
        raise ValueError(f"Invalid GitHub PR URL: {pr_url}")

    owner, repo, number = parsed

    tmp = "/tmp/_ai_senate_comment.md"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(comment)

    result = subprocess.run(
        ["gh", "pr", "comment", str(number), "--repo", f"{owner}/{repo}",
         "--body-file", tmp],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise ValueError(f"gh pr comment failed: {result.stderr[:300]}")

    return result.stdout.strip()