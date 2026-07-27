"""スキャン結果のデータモデル。

アダプタはここで定義した型だけを返す。レンダラはここで定義した型だけを読む。
両者が直接知り合わないので、ツール追加はアダプタの追加だけで済む。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


# 設定の優先順位。数値が大きいほど強い（後勝ち）。
SCOPE_RANK = {
    "user": 10,        # ~/.claude/CLAUDE.md など、全プロジェクト共通
    "project": 20,     # <repo>/CLAUDE.md、リポジトリで共有
    "local": 30,       # settings.local.json、個人ローカル
    "enterprise": 40,  # 組織のマネージド設定
}


@dataclass
class ConfigFile:
    """指示ファイル・設定ファイル1件。"""

    path: Path
    tool: str          # アダプタ名 (claude-code / codex / ...)
    kind: str          # instructions / settings / skill / agent / mcp / rules
    scope: str         # SCOPE_RANK のキー
    size: int = 0
    mtime: float = 0.0
    lines: int = 0
    label: str = ""    # 表示用の補足（スキル名など）

    # inspect.py が中身から取り出した「何を規定しているか」
    declares: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    # gitinfo.py が判定した追跡状態
    git_state: str = "none"          # tracked / untracked / none
    repo_root: Path | None = None

    # クリックで開くための本文。共有モードでは埋め込まない。
    content: str = ""
    truncated: bool = False
    uid: str = ""                    # HTML 側で本文を引くためのキー

    # secrets.py が見つけた平文の認証情報。隠さず、件数と手掛かりだけ持つ。
    secrets: list = field(default_factory=list)

    @property
    def rank(self) -> int:
        return SCOPE_RANK.get(self.scope, 0)

    @property
    def name(self) -> str:
        return self.path.name


@dataclass
class Issue:
    """設定が散らかっている兆候。断定はせず、確認対象として並べる。"""

    severity: str      # high / mid / low
    title: str
    detail: str
    paths: list[Path] = field(default_factory=list)


@dataclass
class TreeNode:
    """ツリー表示の1ノード。ディレクトリを表す。"""

    path: Path
    depth: int
    is_repo: bool = False
    repo_label: str = ""
    repo_info: str = ""
    configs: list[ConfigFile] = field(default_factory=list)
    children: list["TreeNode"] = field(default_factory=list)


@dataclass
class Trigger:
    """自動発火するもの1件。フック・スケジュール・常駐の別を kind で持つ。"""

    kind: str          # hook / schedule / daemon
    event: str         # SessionStart / PreToolUse / cron式 など
    matcher: str       # 対象ツールのパターン。無ければ空
    command: str       # 実行される内容
    source: Path       # どのファイルに書かれていたか
    tool: str = ""
    scope: str = "user"

    @property
    def short_command(self) -> str:
        c = " ".join(self.command.split())
        return c if len(c) <= 160 else c[:157] + "…"


@dataclass
class McpServer:
    name: str
    transport: str     # stdio / http / sse
    detail: str        # コマンドまたは URL
    source: Path
    tool: str = ""
    scope: str = "user"


@dataclass
class ArtifactStore:
    """成果物・中間生成物の格納先1件。"""

    path: Path
    kind: str          # deliverables / engagements / research / graph / scratch
    size: int = 0
    file_count: int = 0
    mtime: float = 0.0
    has_index: bool = False
    note: str = ""


@dataclass
class Violation:
    """置き場ルールに反していそうなファイル。断定はせず候補として出す。"""

    path: Path
    reason: str


@dataclass
class DiskUsage:
    path: Path
    label: str
    size: int
    children: list["DiskUsage"] = field(default_factory=list)


@dataclass
class Project:
    """AI 設定を持つディレクトリ1件。"""

    root: Path
    tools: set[str] = field(default_factory=set)
    configs: list[ConfigFile] = field(default_factory=list)
    triggers: list[Trigger] = field(default_factory=list)
    stores: list[ArtifactStore] = field(default_factory=list)


@dataclass
class ScanResult:
    scanned_at: str
    home: Path
    roots: list[Path]
    configs: list[ConfigFile] = field(default_factory=list)
    triggers: list[Trigger] = field(default_factory=list)
    mcp_servers: list[McpServer] = field(default_factory=list)
    stores: list[ArtifactStore] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    disk: list[DiskUsage] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    tree: list[TreeNode] = field(default_factory=list)
    repos: list = field(default_factory=list)      # gitinfo.GitRepo
    issues: list[Issue] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        def enc(o: Any) -> Any:
            if isinstance(o, Path):
                return str(o)
            if isinstance(o, set):
                return sorted(o)
            if isinstance(o, list):
                return [enc(x) for x in o]
            if isinstance(o, dict):
                return {k: enc(v) for k, v in o.items()}
            if hasattr(o, "__dataclass_fields__"):
                return enc(asdict(o))
            return o

        return enc(self)
