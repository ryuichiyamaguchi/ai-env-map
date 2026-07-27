"""git リポジトリの階層と、設定ファイルが追跡されているかを調べる。

設定ファイルが git 管理下にあるかどうかは重要な情報になる。追跡されていない
CLAUDE.md はチームに共有されない個人設定であり、追跡されている CLAUDE.md は
全員に効く。同じ見た目のファイルでも意味がまったく違う。
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GitRepo:
    root: Path
    branch: str = ""
    remote: str = ""
    dirty: int = 0
    untracked: int = 0
    last_commit: str = ""
    is_submodule: bool = False
    is_worktree: bool = False
    parent_repo: Path | None = None   # 別リポジトリの内側にある場合
    tracked: set[str] = field(default_factory=set)  # リポジトリ相対パス

    @property
    def depth_label(self) -> str:
        if self.is_submodule:
            return "サブモジュール"
        if self.is_worktree:
            return "ワークツリー"
        if self.parent_repo:
            return "入れ子"
        return "リポジトリ"


def _git(root: Path, *args: str, timeout: int = 20) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def _load_repo(root: Path, want_tracked: bool = True) -> GitRepo:
    dotgit = root / ".git"
    repo = GitRepo(
        root=root,
        is_submodule=dotgit.is_file(),
        is_worktree=dotgit.is_file() and "worktrees" in (
            dotgit.read_text(errors="replace") if dotgit.is_file() else ""),
    )
    repo.branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD") or "(コミットなし)"
    repo.remote = _git(root, "remote", "get-url", "origin")
    status = _git(root, "status", "--porcelain")
    if status:
        for line in status.splitlines():
            if line.startswith("??"):
                repo.untracked += 1
            else:
                repo.dirty += 1
    repo.last_commit = _git(root, "log", "-1", "--format=%cd", "--date=short")
    if want_tracked:
        files = _git(root, "ls-files")
        if files:
            repo.tracked = set(files.splitlines())
    return repo


def find_repos(candidates: list[Path], home: Path) -> list[GitRepo]:
    """候補ディレクトリとその祖先から git リポジトリを見つける。"""
    roots: set[Path] = set()
    for c in candidates:
        d = c
        while True:
            if (d / ".git").exists():
                roots.add(d)
            if d == home or d.parent == d:
                break
            d = d.parent

    repos = [_load_repo(r) for r in sorted(roots)]
    by_root = {r.root: r for r in repos}
    for r in repos:
        p = r.root.parent
        while True:
            if p in by_root:
                r.parent_repo = p
                break
            if p == home or p.parent == p:
                break
            p = p.parent
    return repos


def tracking_state(path: Path, repos: list[GitRepo]) -> tuple[str, Path | None]:
    """ファイルが属するリポジトリと追跡状態を返す。

    戻り値は ("tracked" | "untracked" | "none", リポジトリのルート)。
    "none" はどのリポジトリにも属さない、つまりバージョン管理されていない状態。
    """
    best: GitRepo | None = None
    for r in repos:
        try:
            path.relative_to(r.root)
        except ValueError:
            continue
        if best is None or len(str(r.root)) > len(str(best.root)):
            best = r
    if best is None:
        return "none", None
    rel = str(path.relative_to(best.root))
    return ("tracked" if rel in best.tracked else "untracked"), best.root
