"""ファイルシステムの走査とスキャン結果の組み立て。"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from .adapters import ADAPTERS, TOOL_HOME_DIRS
from .gitinfo import find_repos, tracking_state
from .inspect import inspect_config
from .secrets import scan_text
from .model import (
    ArtifactStore, ConfigFile, DiskUsage, Issue, McpServer, Project, ScanResult,
    Trigger, TreeNode, Violation,
)

# 走査から外すディレクトリ名。生成物と巨大な OS 領域を落とす。
PRUNE_NAMES = {
    "node_modules", ".git", ".venv", "venv", "env", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "dist", "build", ".next", ".nuxt", "target",
    "Library", "Applications", ".Trash", ".npm", ".cache", ".bun", ".rustup",
    ".cargo", "Pictures", "Movies", "Music", ".gradle", ".m2", "vendor",
    ".terraform", "site-packages", ".DS_Store",
}

PROJECT_MARKERS = (
    "CLAUDE.md", "AGENTS.md", "GEMINI.md", ".claude", ".cursorrules",
    ".cursor", "opencode.json", "opencode.jsonc", ".mcp.json",
    ".windsurfrules", ".windsurf", ".clinerules", ".aider.conf.yml",
    "CONVENTIONS.md", ".github",
)

STORE_DIR_KINDS = {
    "Deliverables": "deliverables",
    "engagements": "engagements",
    "graphify-out": "graph",
    "research": "research",
}

LOOSE_EXTS = {
    ".html", ".htm", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".mp4", ".mov", ".webm", ".m4a", ".wav", ".pdf",
}


def _dir_size(path: Path) -> int:
    du = shutil.which("du")
    if du:
        try:
            out = subprocess.run([du, "-sk", str(path)], capture_output=True,
                                 text=True, timeout=180)
            if out.returncode == 0 and out.stdout.strip():
                return int(out.stdout.split()[0]) * 1024
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                continue
    return total


def _count_files(path: Path, cap: int = 20000) -> int:
    n = 0
    for _root, _dirs, files in os.walk(path, onerror=lambda e: None):
        n += len(files)
        if n >= cap:
            break
    return n


def find_project_roots(home: Path, max_depth: int = 5) -> list[Path]:
    roots: list[Path] = []
    seen: set[Path] = set()

    def walk(d: Path, depth: int) -> None:
        if depth > max_depth or d in seen:
            return
        seen.add(d)
        try:
            entries = list(os.scandir(d))
        except OSError:
            return
        names = {e.name for e in entries}
        if any(m in names for m in PROJECT_MARKERS) and d != home:
            roots.append(d)
        for e in entries:
            if not e.is_dir(follow_symlinks=False):
                continue
            if e.name in PRUNE_NAMES or (e.name.startswith(".") and e.name not in
                                         (".claude", ".cursor", ".gemini", ".sena",
                                          ".github", ".windsurf", ".clinerules",
                                          ".continue", ".codex")):
                continue
            walk(Path(e.path), depth + 1)

    walk(home, 0)
    return sorted(roots)


def find_stores(home: Path, roots: list[Path], max_depth: int = 6) -> list[ArtifactStore]:
    found: dict[Path, str] = {}

    def walk(d: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = list(os.scandir(d))
        except OSError:
            return
        for e in entries:
            if not e.is_dir(follow_symlinks=False) or e.name in PRUNE_NAMES:
                continue
            p = Path(e.path)
            kind = STORE_DIR_KINDS.get(e.name)
            if kind == "research" and not (p.parent / ".hyperresearch").is_dir():
                kind = None
            if kind:
                found.setdefault(p, kind)
                continue
            if e.name.startswith(".") and e.name not in (".sena",):
                continue
            walk(p, depth + 1)

    walk(home, 0)
    stores: list[ArtifactStore] = []
    for p, kind in sorted(found.items()):
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = 0.0
        stores.append(ArtifactStore(
            path=p, kind=kind, size=_dir_size(p), file_count=_count_files(p),
            mtime=mtime, has_index=(p / "INDEX.md").is_file(),
        ))
    return stores


def find_violations(roots: list[Path]) -> list[Violation]:
    out: list[Violation] = []
    for root in roots:
        try:
            entries = list(os.scandir(root))
        except OSError:
            continue
        for e in entries:
            if not e.is_file(follow_symlinks=False):
                continue
            ext = Path(e.name).suffix.lower()
            if ext not in LOOSE_EXTS:
                continue
            if e.name.lower() in ("readme.pdf", "logo.png", "icon.png", "favicon.svg"):
                continue
            out.append(Violation(path=Path(e.path),
                                 reason=f"プロジェクト直下の {ext} ファイル"))
    return out


def disk_usage(home: Path) -> list[DiskUsage]:
    result: list[DiskUsage] = []
    for rel, label in TOOL_HOME_DIRS:
        p = home / rel
        if not p.is_dir():
            continue
        total = _dir_size(p)
        children: list[DiskUsage] = []
        try:
            for e in os.scandir(p):
                if e.is_dir(follow_symlinks=False):
                    children.append(DiskUsage(path=Path(e.path), label=e.name,
                                              size=_dir_size(Path(e.path))))
                elif e.is_file(follow_symlinks=False):
                    try:
                        sz = e.stat().st_size
                    except OSError:
                        continue
                    if sz > 1_000_000:
                        children.append(DiskUsage(path=Path(e.path), label=e.name, size=sz))
        except OSError:
            pass
        children.sort(key=lambda c: -c.size)
        result.append(DiskUsage(path=p, label=label, size=total, children=children[:12]))
    result.sort(key=lambda d: -d.size)
    return result


# --------------------------------------------------------------------------
# 階層ツリーの構築
# --------------------------------------------------------------------------

def build_tree(home: Path, configs: list[ConfigFile], repos: list) -> list[TreeNode]:
    """設定ファイルと git リポジトリの位置から、必要な枝だけのツリーを作る。

    ホームの全ディレクトリを描いても読めない。設定ファイルかリポジトリが
    存在する枝だけを残し、途中の空ディレクトリは経路として通すだけにする。
    """
    repo_by_root = {r.root: r for r in repos}
    interesting: set[Path] = {c.path.parent for c in configs} | set(repo_by_root)

    # 経路上の祖先をすべて含める
    needed: set[Path] = set()
    for d in interesting:
        cur = d
        while True:
            needed.add(cur)
            if cur == home or cur.parent == cur:
                break
            cur = cur.parent
            try:
                cur.relative_to(home)
            except ValueError:
                break

    configs_by_dir: dict[Path, list[ConfigFile]] = defaultdict(list)
    for c in configs:
        configs_by_dir[c.path.parent].append(c)

    def make(d: Path, depth: int) -> TreeNode:
        repo = repo_by_root.get(d)
        node = TreeNode(path=d, depth=depth, is_repo=repo is not None)
        if repo:
            node.repo_label = repo.depth_label
            bits = [repo.branch]
            if repo.dirty:
                bits.append(f"未コミット {repo.dirty}")
            if repo.untracked:
                bits.append(f"未追跡 {repo.untracked}")
            if repo.last_commit:
                bits.append(repo.last_commit)
            if not repo.remote:
                bits.append("リモートなし")
            node.repo_info = " · ".join(bits)
        node.configs = sorted(configs_by_dir.get(d, []),
                              key=lambda c: (c.kind != "instructions", c.name))
        kids = sorted(x for x in needed if x.parent == d and x != d)
        node.children = [make(k, depth + 1) for k in kids]
        return node

    return [make(home, 0)]


# --------------------------------------------------------------------------
# 散らかりの検出
# --------------------------------------------------------------------------

def detect_issues(home: Path, configs: list[ConfigFile], repos: list) -> list[Issue]:
    issues: list[Issue] = []
    now = datetime.now()

    # 1. 同じディレクトリに CLAUDE.md と AGENTS.md が併存 → 内容がずれる
    by_dir: dict[Path, dict[str, ConfigFile]] = defaultdict(dict)
    for c in configs:
        if c.kind == "instructions":
            by_dir[c.path.parent][c.name] = c
    coexist: list[tuple[Path, list[ConfigFile], int]] = []
    for d, files in sorted(by_dir.items()):
        pair = [files[n] for n in ("CLAUDE.md", "AGENTS.md", "GEMINI.md") if n in files]
        if len(pair) >= 2:
            coexist.append((d, pair, max(p.lines for p in pair) - min(p.lines for p in pair)))
    if coexist:
        worst = max(c[2] for c in coexist)
        sample = "、".join(
            f"{d.name or '~'}（{'+'.join(p.name.split('.')[0] for p in pair)}、行数差 {drift}）"
            for d, pair, drift in sorted(coexist, key=lambda c: -c[2])[:4]
        )
        issues.append(Issue(
            severity="high" if worst > 30 else "mid",
            title="指示ファイルの併存",
            detail=f"{len(coexist)} 箇所で CLAUDE.md と AGENTS.md 等が同居している。"
                   f"行数差が大きい順に {sample}。"
                   "片方だけ更新されて内容がずれていないか確認する。",
            paths=[p.path for _d, pair, _drift in coexist for p in pair],
        ))

    # 2. リポジトリ内なのに git 未追跡の設定ファイル → チームに共有されない
    untracked = [c for c in configs
                 if c.git_state == "untracked" and c.kind in ("instructions", "settings")
                 and "settings.local" not in c.name]
    if untracked:
        issues.append(Issue(
            severity="mid",
            title="git 未追跡の設定ファイル",
            detail=f"{len(untracked)} 件がリポジトリ内にありながらコミットされていない。"
                   "個人だけに効いている状態で、共有すべきものが漏れていないか確認する。",
            paths=[c.path for c in untracked],
        ))

    # 3. 同名スキルが複数の階層に存在 → どちらが効くか分かりにくい
    skills: dict[str, list[ConfigFile]] = defaultdict(list)
    for c in configs:
        if c.kind == "skill" and c.label:
            skills[c.label].append(c)
    dupes = {k: v for k, v in skills.items() if len(v) > 1}
    if dupes:
        issues.append(Issue(
            severity="high",
            title="同名スキルの重複",
            detail="同じ名前のスキルが複数の階層にある: "
                   + ", ".join(f"{k}（{len(v)}箇所）" for k, v in sorted(dupes.items())[:8])
                   + "。プロジェクト側がユーザー側を隠すため、意図しない方が動く恐れがある。",
            paths=[c.path for v in dupes.values() for c in v],
        ))

    # 4. 1年以上更新されていない指示ファイル → 陳腐化
    stale_cut = (now - timedelta(days=365)).timestamp()
    stale = [c for c in configs
             if c.kind in ("instructions", "rules") and 0 < c.mtime < stale_cut]
    if stale:
        issues.append(Issue(
            severity="low",
            title="1年以上更新のない指示ファイル",
            detail=f"{len(stale)} 件。現状と食い違ったまま効き続けていないか確認する。",
            paths=[c.path for c in stale],
        ))

    # 5. 入れ子リポジトリ → 親から見ると中身が追跡されない
    nested = [r for r in repos if r.parent_repo and not r.is_submodule]
    if nested:
        issues.append(Issue(
            severity="mid",
            title="サブモジュールでない入れ子リポジトリ",
            detail=f"{len(nested)} 件。親リポジトリからは中身が追跡されず、"
                   "設定ファイルの変更履歴が親側に残らない。",
            paths=[r.root for r in nested],
        ))

    # 6. 中身のない設定ファイル → 消し忘れ
    empty = [c for c in configs
             if not c.declares and not c.stats and c.kind in ("instructions", "settings")]
    if empty:
        issues.append(Issue(
            severity="low",
            title="中身のない設定ファイル",
            detail=f"{len(empty)} 件。何も規定していないので、消してよいか確認する。",
            paths=[c.path for c in empty],
        ))

    # 7. 平文の認証情報 → 隠さず知らせる。設定の衛生状態そのもの
    with_secrets = [c for c in configs if c.secrets]
    if with_secrets:
        total = sum(len(c.secrets) for c in with_secrets)
        kinds = sorted({s.kind for c in with_secrets for s in c.secrets})
        issues.append(Issue(
            severity="high",
            title="平文の認証情報",
            detail=f"{len(with_secrets)} ファイルに計 {total} 件（{'、'.join(kinds)}）。"
                   "設定ファイルに直接書かれている。環境変数や秘密情報の保管庫へ"
                   "移せないか確認する。なおこの出力では値を伏せていないため、"
                   "伏字なしの HTML は共有しないこと。",
            paths=[c.path for c in with_secrets],
        ))

    # 8. 巨大な指示ファイル → 毎回読まれる分だけ重い
    heavy = [c for c in configs if c.kind in ("instructions", "rules") and c.lines > 200]
    if heavy:
        issues.append(Issue(
            severity="mid",
            title="肥大化した指示ファイル",
            detail=f"{len(heavy)} 件が 200 行超。"
                   "該当ツールの起動ごとに読み込まれるため、分割か削減を検討する。",
            paths=[c.path for c in heavy],
        ))

    order = {"high": 0, "mid": 1, "low": 2}
    issues.sort(key=lambda i: order.get(i.severity, 3))
    return issues


# --------------------------------------------------------------------------

def scan(home: Path | None = None, max_depth: int = 5,
         skip_sizes: bool = False, skip_content: bool = False) -> ScanResult:
    home = (home or Path.home()).resolve()
    started = time.time()
    roots = find_project_roots(home, max_depth=max_depth)

    configs: list[ConfigFile] = []
    triggers: list[Trigger] = []
    mcp: list[McpServer] = []
    errors: list[str] = []

    for adapter in ADAPTERS:
        try:
            configs.extend(adapter.global_configs(home))
            for root in roots:
                configs.extend(adapter.project_configs(root))
            triggers.extend(adapter.triggers(home, roots))
            mcp.extend(adapter.mcp_servers(home, roots))
        except Exception as exc:
            errors.append(f"{adapter.name}: {type(exc).__name__}: {exc}")

    # 同じファイルを複数のアダプタが拾った場合に備えて重複を落とす
    uniq: dict[Path, ConfigFile] = {}
    for c in configs:
        uniq.setdefault(c.path, c)
    configs = sorted(uniq.values(), key=lambda c: str(c.path))

    # 中身を読んで「何を規定しているか」を埋める。あわせてクリック表示用の
    # 本文も持たせる。1ファイル 80,000 文字で頭打ちにして、巨大な設定ファイル
    # 1つで出力 HTML が膨れないようにする。
    for i, c in enumerate(configs):
        c.declares, c.stats = inspect_config(c.path, c.kind)
        c.uid = f"f{i}"
        if not skip_content:
            try:
                body = c.path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                body = ""
            if len(body) > 80_000:
                c.content, c.truncated = body[:80_000], True
            else:
                c.content = body
            # 平文の認証情報は隠さず、見つけた事実だけを記録する。
            c.secrets = scan_text(body)

    # git の階層と追跡状態
    repos = find_repos([c.path.parent for c in configs] + roots, home)
    for c in configs:
        c.git_state, c.repo_root = tracking_state(c.path, repos)

    by_root: dict[Path, Project] = {r: Project(root=r) for r in roots}
    for c in configs:
        for r in roots:
            try:
                c.path.relative_to(r)
            except ValueError:
                continue
            by_root[r].configs.append(c)
            by_root[r].tools.add(c.tool)
    for t in triggers:
        for r in roots:
            try:
                t.source.relative_to(r)
            except ValueError:
                continue
            by_root[r].triggers.append(t)

    stores = [] if skip_sizes else find_stores(home, roots)
    for s in stores:
        for r in roots:
            try:
                s.path.relative_to(r)
            except ValueError:
                continue
            by_root[r].stores.append(s)

    result = ScanResult(
        scanned_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        home=home,
        roots=roots,
        configs=configs,
        triggers=triggers,
        mcp_servers=mcp,
        stores=stores,
        violations=find_violations(roots),
        disk=[] if skip_sizes else disk_usage(home),
        projects=[p for p in by_root.values() if p.configs or p.triggers or p.stores],
        errors=errors,
        repos=repos,
        tree=build_tree(home, configs, repos),
        issues=detect_issues(home, configs, repos),
    )
    result.errors.append(f"走査時間 {time.time() - started:.1f} 秒")
    return result
