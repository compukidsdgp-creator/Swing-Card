"""Optional: push batch files to your GitHub repo so the scheduled Action can keep them updated.

Configure in Streamlit secrets (.streamlit/secrets.toml or the Cloud "Secrets" box):
    GITHUB_TOKEN = "ghp_..."            # fine-grained token with Contents: read & write
    GITHUB_REPO  = "yourname/swingscope-tracker"
    GITHUB_BRANCH = "main"              # optional
"""
from __future__ import annotations

import base64
from pathlib import Path

import requests

API = "https://api.github.com"


def _cfg(secrets) -> tuple[str, str, str] | None:
    try:
        tok, repo = secrets.get("GITHUB_TOKEN"), secrets.get("GITHUB_REPO")
        br = secrets.get("GITHUB_BRANCH", "main")
    except Exception:
        return None
    return (tok, repo, br) if tok and repo else None


def enabled(secrets) -> bool:
    return _cfg(secrets) is not None


def push_files(secrets, files: dict[str, Path], message: str) -> list[str]:
    """files: {repo_path: local_path}. Returns list of status lines."""
    cfg = _cfg(secrets)
    if not cfg:
        return ["GitHub sync not configured"]
    tok, repo, br = cfg
    h = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}
    out = []
    for rpath, lpath in files.items():
        url = f"{API}/repos/{repo}/contents/{rpath}"
        sha = None
        r = requests.get(url, headers=h, params={"ref": br}, timeout=20)
        if r.status_code == 200:
            sha = r.json().get("sha")
        body = {"message": message, "branch": br,
                "content": base64.b64encode(Path(lpath).read_bytes()).decode()}
        if sha:
            body["sha"] = sha
        r = requests.put(url, headers=h, json=body, timeout=30)
        out.append(f"{rpath}: {'ok' if r.status_code in (200, 201) else r.status_code}")
    return out
