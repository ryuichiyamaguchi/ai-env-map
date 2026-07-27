"""設定ファイルの中身を読んで「何を規定しているか」を取り出す。

行数やバイト数は中身を語らない。CLAUDE.md なら何という見出しで何を指示して
いるのか、settings.json なら何を許可して何を禁じ、何を自動実行するのか。
ここで抽出した内容がツリー上の各ノードの説明文になる。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .adapters import _read_json, _read_toml

# 強い指示の目印。数が多いほど「重い」指示ファイル。
EMPHASIS_RE = re.compile(r"\b(IMPORTANT|NEVER|MUST|ALWAYS|禁止|必ず|絶対)\b")


def _front_matter(text: str) -> tuple[dict[str, str], str]:
    """YAML フロントマターを雑に読む。ネストは扱わない。"""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    head, body = text[3:end], text[end + 4:]
    meta: dict[str, str] = {}
    key = None
    for line in head.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if m:
            key = m.group(1)
            meta[key] = m.group(2).strip().strip("'\"")
        elif key and line.startswith((" ", "\t")):
            meta[key] = (meta.get(key, "") + " " + line.strip()).strip()
    return meta, body


def inspect_markdown_instructions(path: Path) -> tuple[list[str], dict]:
    """CLAUDE.md / AGENTS.md / rules/*.md — 見出しを「規定している事柄」とみなす。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], {}
    _meta, body = _front_matter(text)
    headings = [
        re.sub(r"\s*\{#.*\}$", "", m.group(2)).strip()
        for m in re.finditer(r"^(#{1,3})\s+(.+?)\s*$", body, re.MULTILINE)
    ]
    stats = {
        "見出し": len(headings),
        "強調指示": len(EMPHASIS_RE.findall(body)),
        "箇条書き": len(re.findall(r"^\s*[-*]\s+", body, re.MULTILINE)),
        "参照": len(re.findall(r"@[\w./-]+\.md", body)),
    }
    return headings, {k: v for k, v in stats.items() if v}


def inspect_settings(path: Path) -> tuple[list[str], dict]:
    """settings.json — 許可・拒否・フック・環境変数・モデル指定を数える。"""
    data = _read_json(path)
    if not isinstance(data, dict):
        return ["読み取り失敗"], {}
    declares: list[str] = []
    stats: dict[str, int | str] = {}

    perms = data.get("permissions")
    if isinstance(perms, dict):
        for key, label in (("allow", "許可"), ("deny", "拒否"), ("ask", "確認")):
            v = perms.get(key)
            if isinstance(v, list) and v:
                stats[label] = len(v)
        if perms.get("defaultMode"):
            declares.append(f"既定モード {perms['defaultMode']}")
        for key, label in (("additionalDirectories", "追加ディレクトリ"),):
            v = perms.get(key)
            if isinstance(v, list) and v:
                stats[label] = len(v)

    hooks = data.get("hooks")
    if isinstance(hooks, dict):
        events = [e for e, v in hooks.items() if isinstance(v, list) and v]
        if events:
            n = sum(len(h.get("hooks", []) or [])
                    for v in hooks.values() if isinstance(v, list)
                    for h in v if isinstance(h, dict))
            stats["フック"] = n
            declares.append("自動実行: " + " / ".join(events))

    env = data.get("env")
    if isinstance(env, dict) and env:
        stats["環境変数"] = len(env)
        declares.append("環境変数: " + ", ".join(list(env)[:6]))

    for key, label in (("model", "モデル"), ("statusLine", "ステータスライン"),
                       ("outputStyle", "出力スタイル"), ("cleanupPeriodDays", "保持日数")):
        v = data.get(key)
        if isinstance(v, dict):
            v = v.get("command") or v.get("type") or "設定あり"
        if v:
            declares.append(f"{label} {v}")

    mcp = data.get("mcpServers")
    if isinstance(mcp, dict) and mcp:
        stats["MCP"] = len(mcp)
        declares.append("MCP: " + ", ".join(list(mcp)[:6]))

    plugins = data.get("enabledPlugins") or data.get("plugins")
    if isinstance(plugins, (dict, list)) and plugins:
        stats["プラグイン"] = len(plugins)

    if not declares and not stats:
        declares.append("空、または未知のキーのみ")
    return declares, stats


def inspect_skill(path: Path) -> tuple[list[str], dict]:
    """SKILL.md — フロントマターの description が発動条件そのもの。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], {}
    meta, body = _front_matter(text)
    declares = []
    desc = meta.get("description", "")
    if desc:
        declares.append(desc[:160] + ("…" if len(desc) > 160 else ""))
    stats: dict[str, int | str] = {}
    if meta.get("allowed-tools"):
        stats["許可ツール"] = len(meta["allowed-tools"].split(","))
    if meta.get("model"):
        stats["モデル"] = meta["model"]
    stats["行数"] = body.count("\n") + 1
    return declares, stats


def inspect_agent(path: Path) -> tuple[list[str], dict]:
    """agents/*.md — 役割・モデル・使えるツールが本体。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], {}
    meta, body = _front_matter(text)
    declares = []
    desc = meta.get("description", "")
    if desc:
        declares.append(desc[:160] + ("…" if len(desc) > 160 else ""))
    stats: dict[str, int | str] = {}
    if meta.get("model"):
        stats["モデル"] = meta["model"]
    tools = meta.get("tools", "")
    if tools:
        stats["ツール"] = "全て" if tools.strip() == "*" else len(tools.split(","))
    stats["行数"] = body.count("\n") + 1
    return declares, stats


def inspect_toml_config(path: Path) -> tuple[list[str], dict]:
    """Codex の config.toml。"""
    data = _read_toml(path)
    if not isinstance(data, dict):
        return ["読み取り失敗"], {}
    declares, stats = [], {}
    if data.get("model"):
        declares.append(f"モデル {data['model']}")
    if data.get("approval_policy"):
        declares.append(f"承認 {data['approval_policy']}")
    if data.get("sandbox_mode"):
        declares.append(f"サンドボックス {data['sandbox_mode']}")
    mcp = data.get("mcp_servers")
    if isinstance(mcp, dict) and mcp:
        stats["MCP"] = len(mcp)
        declares.append("MCP: " + ", ".join(list(mcp)[:6]))
    profiles = data.get("profiles")
    if isinstance(profiles, dict) and profiles:
        stats["プロファイル"] = len(profiles)
    return declares, stats


INSPECTORS = {
    "instructions": inspect_markdown_instructions,
    "rules": inspect_markdown_instructions,
    "skill": inspect_skill,
    "agent": inspect_agent,
}


def inspect_config(path: Path, kind: str) -> tuple[list[str], dict]:
    """種別に応じた抽出を行う。失敗しても例外は投げない。"""
    try:
        if kind in INSPECTORS:
            result = INSPECTORS[kind](path)
            # 指示ファイルは見出しがそのまま「規定している事柄」になる
            if kind in ("instructions", "rules"):
                headings, stats = result
                return headings, stats
            return result
        if path.suffix == ".toml":
            return inspect_toml_config(path)
        if path.suffix == ".json":
            return inspect_settings(path)
    except Exception:
        return ["解析に失敗"], {}
    return [], {}
