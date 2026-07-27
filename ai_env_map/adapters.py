"""ツール別アダプタ。

新しい AI ツールへの対応は、ここに ToolAdapter のサブクラスを1つ足して
ADAPTERS に登録するだけで完結する。scan.py と render.py は触らない。
"""

from __future__ import annotations

import json
import os
import plistlib
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Iterator

from .model import ConfigFile, McpServer, Trigger


def app_data_dirs(home: Path) -> list[Path]:
    """OS ごとのアプリ設定の置き場。同じツールでも場所が違う。"""
    dirs: list[Path] = []
    if sys.platform == "win32":
        for var in ("APPDATA", "LOCALAPPDATA"):
            v = os.environ.get(var)
            if v:
                dirs.append(Path(v))
    elif sys.platform == "darwin":
        dirs.append(home / "Library" / "Application Support")
        dirs.append(home / ".config")
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        dirs.append(Path(xdg) if xdg else home / ".config")
    return [d for d in dirs if d.is_dir()]


def _read_json(path: Path) -> dict | None:
    """コメント付き JSON や壊れた JSON でも落とさずに読む。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # JSONC 相当。行コメントと末尾カンマだけ落として再挑戦する。
        stripped = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
        stripped = re.sub(r",(\s*[}\]])", r"\1", stripped)
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return None


def _read_toml(path: Path) -> dict | None:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return None


def _stat(path: Path) -> tuple[int, float, int]:
    """(バイト数, 更新時刻, 行数) を返す。テキストでなければ行数は 0。"""
    try:
        st = path.stat()
    except OSError:
        return 0, 0.0, 0
    lines = 0
    if st.st_size < 4_000_000:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").count("\n") + 1
        except OSError:
            lines = 0
    return st.st_size, st.st_mtime, lines


def _cfg(path: Path, tool: str, kind: str, scope: str, label: str = "") -> ConfigFile:
    size, mtime, lines = _stat(path)
    return ConfigFile(
        path=path, tool=tool, kind=kind, scope=scope,
        size=size, mtime=mtime, lines=lines, label=label,
    )


def _hook_command(spec: dict) -> str:
    """フック1件の実行内容を組み立てる。

    Claude Code 形式は command と args が分かれることがあり、command だけ読むと
    "/bin/bash" のように中身の消えた表示になる。args まで連結して実体を出す。
    """
    cmd = str(spec.get("command", "") or spec.get("type", "") or "")
    args = spec.get("args")
    if isinstance(args, list) and args:
        cmd = " ".join([cmd] + [str(a) for a in args])
    return cmd.strip()


def parse_claude_style_hooks(path: Path, tool: str, scope: str) -> Iterator[Trigger]:
    """{"hooks": {"<イベント>": [{"matcher":…, "hooks":[…]}]}} 形式を読む。

    Claude Code の settings.json、Codex の hooks.json、Gemini の settings.json が
    同じ形なので共通化してある。
    """
    data = _read_json(path)
    if not isinstance(data, dict):
        return
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            continue  # hooks.state のような非イベントのテーブルを弾く
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            matcher = str(entry.get("matcher", "") or "")
            for h in entry.get("hooks", []) or []:
                if not isinstance(h, dict):
                    continue
                yield Trigger(
                    kind="hook", event=str(event), matcher=matcher,
                    command=_hook_command(h), source=path, tool=tool, scope=scope,
                )


class ToolAdapter:
    """1つの AI ツールの設定レイアウトを表す。"""

    name = ""
    display = ""

    # このディレクトリにあればプロジェクトが当該ツールを使っているとみなす目印
    project_markers: tuple[str, ...] = ()

    def global_configs(self, home: Path) -> Iterator[ConfigFile]:
        return iter(())

    def project_configs(self, root: Path) -> Iterator[ConfigFile]:
        return iter(())

    def triggers(self, home: Path, roots: list[Path]) -> Iterator[Trigger]:
        return iter(())

    def mcp_servers(self, home: Path, roots: list[Path]) -> Iterator[McpServer]:
        return iter(())


# --------------------------------------------------------------------------
# Claude Code
# --------------------------------------------------------------------------

class ClaudeCodeAdapter(ToolAdapter):
    name = "claude-code"
    display = "Claude Code"
    project_markers = ("CLAUDE.md", ".claude")

    def _settings_files(self, base: Path) -> list[tuple[Path, str]]:
        return [
            (base / "settings.json", "project" if base.name == ".claude" else "user"),
            (base / "settings.local.json", "local"),
        ]

    def global_configs(self, home: Path) -> Iterator[ConfigFile]:
        d = home / ".claude"
        if not d.is_dir():
            return
        for f in (d / "CLAUDE.md", home / "CLAUDE.md"):
            if f.is_file():
                yield _cfg(f, self.name, "instructions", "user")
        rules = d / "rules"
        if rules.is_dir():
            for f in sorted(rules.glob("*.md")):
                yield _cfg(f, self.name, "rules", "user", label=f.stem)
        for f, scope in ((d / "settings.json", "user"), (d / "settings.local.json", "local")):
            if f.is_file():
                yield _cfg(f, self.name, "settings", scope)
        skills = d / "skills"
        if skills.is_dir():
            for s in sorted(skills.iterdir()):
                sf = s / "SKILL.md"
                if sf.is_file():
                    yield _cfg(sf, self.name, "skill", "user", label=s.name)
        agents = d / "agents"
        if agents.is_dir():
            for f in sorted(agents.glob("*.md")):
                yield _cfg(f, self.name, "agent", "user", label=f.stem)

    def project_configs(self, root: Path) -> Iterator[ConfigFile]:
        f = root / "CLAUDE.md"
        if f.is_file():
            yield _cfg(f, self.name, "instructions", "project")
        d = root / ".claude"
        if not d.is_dir():
            return
        if (d / "CLAUDE.md").is_file():
            yield _cfg(d / "CLAUDE.md", self.name, "instructions", "project")
        for f, scope in ((d / "settings.json", "project"), (d / "settings.local.json", "local")):
            if f.is_file():
                yield _cfg(f, self.name, "settings", scope)
        for sub, kind in (("skills", "skill"), ("agents", "agent")):
            p = d / sub
            if not p.is_dir():
                continue
            if kind == "skill":
                for s in sorted(p.iterdir()):
                    if (s / "SKILL.md").is_file():
                        yield _cfg(s / "SKILL.md", self.name, kind, "project", label=s.name)
            else:
                for f in sorted(p.glob("*.md")):
                    yield _cfg(f, self.name, kind, "project", label=f.stem)

    def triggers(self, home: Path, roots: list[Path]) -> Iterator[Trigger]:
        d = home / ".claude"
        for f, scope in ((d / "settings.json", "user"), (d / "settings.local.json", "local")):
            if f.is_file():
                yield from parse_claude_style_hooks(f, self.name, scope)
        for root in roots:
            pd = root / ".claude"
            for f, scope in ((pd / "settings.json", "project"), (pd / "settings.local.json", "local")):
                if f.is_file():
                    yield from parse_claude_style_hooks(f, self.name, scope)

    def _mcp_from(self, path: Path, scope: str) -> Iterator[McpServer]:
        data = _read_json(path)
        if not isinstance(data, dict):
            return
        blocks = [data.get("mcpServers")]
        # ~/.claude.json はプロジェクトごとに mcpServers を持つ
        projects = data.get("projects")
        if isinstance(projects, dict):
            blocks.extend(v.get("mcpServers") for v in projects.values() if isinstance(v, dict))
        for block in blocks:
            if not isinstance(block, dict):
                continue
            for name, spec in block.items():
                if not isinstance(spec, dict):
                    continue
                if spec.get("url"):
                    transport, detail = spec.get("type", "http"), str(spec["url"])
                else:
                    transport = "stdio"
                    detail = " ".join([str(spec.get("command", ""))] + [str(a) for a in spec.get("args", []) or []])
                yield McpServer(name=str(name), transport=str(transport), detail=detail.strip(),
                                source=path, tool=self.name, scope=scope)

    def mcp_servers(self, home: Path, roots: list[Path]) -> Iterator[McpServer]:
        for f, scope in ((home / ".claude.json", "user"),
                         (home / ".claude" / "settings.json", "user"),
                         (home / ".claude" / "settings.local.json", "local")):
            if f.is_file():
                yield from self._mcp_from(f, scope)
        for root in roots:
            for f, scope in ((root / ".mcp.json", "project"),
                             (root / ".claude" / "settings.json", "project"),
                             (root / ".claude" / "settings.local.json", "local")):
                if f.is_file():
                    yield from self._mcp_from(f, scope)


# --------------------------------------------------------------------------
# Codex CLI
# --------------------------------------------------------------------------

class CodexAdapter(ToolAdapter):
    name = "codex"
    display = "Codex CLI"
    project_markers = ("AGENTS.md", ".codex")

    def global_configs(self, home: Path) -> Iterator[ConfigFile]:
        d = home / ".codex"
        if not d.is_dir():
            return
        for f in (d / "config.toml", d / "AGENTS.md", d / "instructions.md"):
            if f.is_file():
                kind = "settings" if f.suffix == ".toml" else "instructions"
                yield _cfg(f, self.name, kind, "user")
        for sub, kind in (("skills", "skill"), ("prompts", "skill")):
            p = d / sub
            if not p.is_dir():
                continue
            for s in sorted(p.iterdir()):
                target = s / "SKILL.md" if s.is_dir() else s
                if target.is_file():
                    yield _cfg(target, self.name, kind, "user", label=s.stem)

    def project_configs(self, root: Path) -> Iterator[ConfigFile]:
        f = root / "AGENTS.md"
        if f.is_file():
            yield _cfg(f, self.name, "instructions", "project")

    def triggers(self, home: Path, roots: list[Path]) -> Iterator[Trigger]:
        # 実体のフック定義は hooks.json 側。Claude Code と同じ形をしている。
        hooks_json = home / ".codex" / "hooks.json"
        if hooks_json.is_file():
            yield from parse_claude_style_hooks(hooks_json, self.name, "user")

        cfg = home / ".codex" / "config.toml"
        data = _read_toml(cfg) if cfg.is_file() else None
        if not data:
            return
        # config.toml の [hooks] は承認済みハッシュの保存場所であってイベント定義ではない。
        # ここを読むと state という架空のイベントが生えるので触らない。
        notify = data.get("notify")
        if notify:
            cmd = " ".join(str(x) for x in notify) if isinstance(notify, list) else str(notify)
            yield Trigger(kind="hook", event="ターン終了時", matcher="", command=cmd,
                          source=cfg, tool=self.name, scope="user")

    def mcp_servers(self, home: Path, roots: list[Path]) -> Iterator[McpServer]:
        cfg = home / ".codex" / "config.toml"
        data = _read_toml(cfg) if cfg.is_file() else None
        if not data:
            return
        for name, spec in (data.get("mcp_servers") or {}).items():
            if not isinstance(spec, dict):
                continue
            if spec.get("url"):
                transport, detail = "http", str(spec["url"])
            else:
                transport = "stdio"
                detail = " ".join([str(spec.get("command", ""))] + [str(a) for a in spec.get("args", []) or []])
            yield McpServer(name=str(name), transport=transport, detail=detail.strip(),
                            source=cfg, tool=self.name, scope="user")


# --------------------------------------------------------------------------
# Gemini CLI
# --------------------------------------------------------------------------

class GeminiAdapter(ToolAdapter):
    name = "gemini"
    display = "Gemini CLI"
    project_markers = ("GEMINI.md", ".gemini")

    def global_configs(self, home: Path) -> Iterator[ConfigFile]:
        d = home / ".gemini"
        if not d.is_dir():
            return
        for f in (d / "settings.json", d / "GEMINI.md"):
            if f.is_file():
                kind = "settings" if f.suffix == ".json" else "instructions"
                yield _cfg(f, self.name, kind, "user")

    def project_configs(self, root: Path) -> Iterator[ConfigFile]:
        for f in (root / "GEMINI.md", root / ".gemini" / "settings.json"):
            if f.is_file():
                kind = "settings" if f.suffix == ".json" else "instructions"
                yield _cfg(f, self.name, kind, "project")

    def triggers(self, home: Path, roots: list[Path]) -> Iterator[Trigger]:
        f = home / ".gemini" / "settings.json"
        if f.is_file():
            yield from parse_claude_style_hooks(f, self.name, "user")
        for root in roots:
            pf = root / ".gemini" / "settings.json"
            if pf.is_file():
                yield from parse_claude_style_hooks(pf, self.name, "project")

    def mcp_servers(self, home: Path, roots: list[Path]) -> Iterator[McpServer]:
        f = home / ".gemini" / "settings.json"
        data = _read_json(f) if f.is_file() else None
        if not isinstance(data, dict):
            return
        for name, spec in (data.get("mcpServers") or {}).items():
            if not isinstance(spec, dict):
                continue
            detail = str(spec.get("httpUrl") or spec.get("url") or "")
            transport = "http"
            if not detail:
                transport = "stdio"
                detail = " ".join([str(spec.get("command", ""))] + [str(a) for a in spec.get("args", []) or []])
            yield McpServer(name=str(name), transport=transport, detail=detail.strip(),
                            source=f, tool=self.name, scope="user")


# --------------------------------------------------------------------------
# Cursor / Copilot / opencode — 設定の所在だけを拾う軽量アダプタ
# --------------------------------------------------------------------------

class CursorAdapter(ToolAdapter):
    name = "cursor"
    display = "Cursor"
    project_markers = (".cursorrules", ".cursor")

    def global_configs(self, home: Path) -> Iterator[ConfigFile]:
        f = home / ".cursor" / "mcp.json"
        if f.is_file():
            yield _cfg(f, self.name, "mcp", "user")

    def project_configs(self, root: Path) -> Iterator[ConfigFile]:
        f = root / ".cursorrules"
        if f.is_file():
            yield _cfg(f, self.name, "instructions", "project")
        rules = root / ".cursor" / "rules"
        if rules.is_dir():
            for r in sorted(rules.glob("*.mdc")):
                yield _cfg(r, self.name, "rules", "project", label=r.stem)

    def mcp_servers(self, home: Path, roots: list[Path]) -> Iterator[McpServer]:
        f = home / ".cursor" / "mcp.json"
        data = _read_json(f) if f.is_file() else None
        if not isinstance(data, dict):
            return
        for name, spec in (data.get("mcpServers") or {}).items():
            if not isinstance(spec, dict):
                continue
            detail = str(spec.get("url") or "")
            transport = "http" if detail else "stdio"
            if not detail:
                detail = " ".join([str(spec.get("command", ""))] + [str(a) for a in spec.get("args", []) or []])
            yield McpServer(name=str(name), transport=transport, detail=detail.strip(),
                            source=f, tool=self.name, scope="user")


class CopilotAdapter(ToolAdapter):
    name = "copilot"
    display = "GitHub Copilot"
    project_markers = (".github",)

    def global_configs(self, home: Path) -> Iterator[ConfigFile]:
        d = home / ".copilot"
        if not d.is_dir():
            return
        for f in (d / "config.json", d / "mcp-config.json"):
            if f.is_file():
                yield _cfg(f, self.name, "settings", "user")
        skills = d / "skills"
        if skills.is_dir():
            for s in sorted(skills.iterdir()):
                if (s / "SKILL.md").is_file():
                    yield _cfg(s / "SKILL.md", self.name, "skill", "user", label=s.name)

    def project_configs(self, root: Path) -> Iterator[ConfigFile]:
        gh = root / ".github"
        if not gh.is_dir():
            return
        f = gh / "copilot-instructions.md"
        if f.is_file():
            yield _cfg(f, self.name, "instructions", "project")
        # 適用範囲を絞った指示とプロンプト。どちらも .github 配下に置かれる。
        for sub, pattern, kind in (("instructions", "*.instructions.md", "rules"),
                                   ("prompts", "*.prompt.md", "skill")):
            p = gh / sub
            if p.is_dir():
                for r in sorted(p.glob(pattern)):
                    yield _cfg(r, self.name, kind, "project",
                               label=r.name.split(".")[0])

    def mcp_servers(self, home: Path, roots: list[Path]) -> Iterator[McpServer]:
        for f in (home / ".copilot" / "mcp-config.json",):
            data = _read_json(f) if f.is_file() else None
            if not isinstance(data, dict):
                continue
            for name, spec in (data.get("mcpServers") or {}).items():
                if not isinstance(spec, dict):
                    continue
                detail = str(spec.get("url") or "")
                transport = "http" if detail else "stdio"
                if not detail:
                    detail = " ".join([str(spec.get("command", ""))]
                                      + [str(a) for a in spec.get("args", []) or []])
                yield McpServer(name=str(name), transport=transport,
                                detail=detail.strip(), source=f,
                                tool=self.name, scope="user")


class OpenCodeAdapter(ToolAdapter):
    name = "opencode"
    display = "opencode"
    project_markers = ("opencode.json", "opencode.jsonc")

    def _dirs(self, home: Path) -> list[Path]:
        return [b / "opencode" for b in app_data_dirs(home)] + [home / ".opencode"]

    def global_configs(self, home: Path) -> Iterator[ConfigFile]:
        for d in self._dirs(home):
            if not d.is_dir():
                continue
            for f in (d / "opencode.json", d / "opencode.jsonc", d / "config.json"):
                if f.is_file():
                    yield _cfg(f, self.name, "settings", "user")
            for sub, kind in (("skills", "skill"), ("agent", "agent"),
                              ("command", "skill")):
                p = d / sub
                if not p.is_dir():
                    continue
                for s in sorted(p.iterdir()):
                    target = s / "SKILL.md" if s.is_dir() else s
                    if target.is_file() and target.suffix in (".md", ""):
                        yield _cfg(target, self.name, kind, "user", label=s.stem)

    def project_configs(self, root: Path) -> Iterator[ConfigFile]:
        for f in (root / "opencode.json", root / "opencode.jsonc"):
            if f.is_file():
                yield _cfg(f, self.name, "settings", "project")

    def mcp_servers(self, home: Path, roots: list[Path]) -> Iterator[McpServer]:
        for d in self._dirs(home):
            for f in (d / "opencode.json", d / "opencode.jsonc"):
                data = _read_json(f) if f.is_file() else None
                if not isinstance(data, dict):
                    continue
                for name, spec in (data.get("mcp") or {}).items():
                    if not isinstance(spec, dict):
                        continue
                    cmd = spec.get("command")
                    detail = (" ".join(str(x) for x in cmd) if isinstance(cmd, list)
                              else str(spec.get("url") or cmd or ""))
                    yield McpServer(name=str(name),
                                    transport=str(spec.get("type", "stdio")),
                                    detail=detail.strip(), source=f,
                                    tool=self.name, scope="user")


class WindsurfAdapter(ToolAdapter):
    name = "windsurf"
    display = "Windsurf"
    project_markers = (".windsurfrules", ".windsurf")

    def global_configs(self, home: Path) -> Iterator[ConfigFile]:
        f = home / ".codeium" / "windsurf" / "memories" / "global_rules.md"
        if f.is_file():
            yield _cfg(f, self.name, "instructions", "user")

    def project_configs(self, root: Path) -> Iterator[ConfigFile]:
        f = root / ".windsurfrules"
        if f.is_file():
            yield _cfg(f, self.name, "instructions", "project")
        rules = root / ".windsurf" / "rules"
        if rules.is_dir():
            for r in sorted(rules.glob("*.md")):
                yield _cfg(r, self.name, "rules", "project", label=r.stem)


class ClineAdapter(ToolAdapter):
    name = "cline"
    display = "Cline"
    project_markers = (".clinerules",)

    def project_configs(self, root: Path) -> Iterator[ConfigFile]:
        p = root / ".clinerules"
        if p.is_file():
            yield _cfg(p, self.name, "instructions", "project")
        elif p.is_dir():
            # 新しい書式ではディレクトリに分割して置く
            for r in sorted(p.glob("*.md")):
                yield _cfg(r, self.name, "rules", "project", label=r.stem)


class ZedAdapter(ToolAdapter):
    name = "zed"
    display = "Zed"
    project_markers = (".rules",)

    def global_configs(self, home: Path) -> Iterator[ConfigFile]:
        for base in app_data_dirs(home):
            f = base / "zed" / "settings.json"
            if f.is_file():
                yield _cfg(f, self.name, "settings", "user")

    def project_configs(self, root: Path) -> Iterator[ConfigFile]:
        f = root / ".rules"
        if f.is_file():
            yield _cfg(f, self.name, "instructions", "project")

    def mcp_servers(self, home: Path, roots: list[Path]) -> Iterator[McpServer]:
        for base in app_data_dirs(home):
            f = base / "zed" / "settings.json"
            data = _read_json(f) if f.is_file() else None
            if not isinstance(data, dict):
                continue
            # Zed は context_servers というキーで MCP を持つ
            for name, spec in (data.get("context_servers") or {}).items():
                if not isinstance(spec, dict):
                    continue
                cmd = spec.get("command")
                if isinstance(cmd, dict):
                    detail = " ".join([str(cmd.get("path", ""))]
                                      + [str(a) for a in cmd.get("args", []) or []])
                else:
                    detail = str(cmd or "")
                yield McpServer(name=str(name), transport="stdio",
                                detail=detail.strip(), source=f,
                                tool=self.name, scope="user")


class ContinueAdapter(ToolAdapter):
    name = "continue"
    display = "Continue"
    project_markers = (".continue",)

    def global_configs(self, home: Path) -> Iterator[ConfigFile]:
        d = home / ".continue"
        if not d.is_dir():
            return
        for f in (d / "config.json", d / "config.yaml"):
            if f.is_file():
                yield _cfg(f, self.name, "settings", "user")
        rules = d / "rules"
        if rules.is_dir():
            for r in sorted(rules.glob("*.md")):
                yield _cfg(r, self.name, "rules", "user", label=r.stem)


class AiderAdapter(ToolAdapter):
    name = "aider"
    display = "aider"
    project_markers = (".aider.conf.yml", "CONVENTIONS.md")

    def global_configs(self, home: Path) -> Iterator[ConfigFile]:
        for f in (home / ".aider.conf.yml", home / ".aider.model.settings.yml"):
            if f.is_file():
                yield _cfg(f, self.name, "settings", "user")

    def project_configs(self, root: Path) -> Iterator[ConfigFile]:
        for f, kind in ((root / ".aider.conf.yml", "settings"),
                        (root / "CONVENTIONS.md", "instructions")):
            if f.is_file():
                yield _cfg(f, self.name, kind, "project")


class AgentsMdAdapter(ToolAdapter):
    """AGENTS.md を読む雑多なツール群 (aider / droid / amp など) の受け皿。"""

    name = "agents-md"
    display = "AGENTS.md 系"

    def global_configs(self, home: Path) -> Iterator[ConfigFile]:
        d = home / ".agents"
        if not d.is_dir():
            return
        skills = d / "skills"
        if skills.is_dir():
            for s in sorted(skills.iterdir()):
                if (s / "SKILL.md").is_file():
                    yield _cfg(s / "SKILL.md", self.name, "skill", "user", label=s.name)


# --------------------------------------------------------------------------
# OS のスケジューラ — AI ツールを呼ぶものだけ拾う
# --------------------------------------------------------------------------

_AI_HINT = re.compile(
    r"claude|codex|gemini|cursor|copilot|opencode|aider|graphify|hyperresearch|"
    r"anthropic|openai|ollama|sena|zena|bungo|agent",
    re.IGNORECASE,
)


class SystemScheduleAdapter(ToolAdapter):
    """OS のスケジューラのうち、AI ツールに触れるものだけを拾う。

    macOS は launchd、Linux は systemd のユーザーユニット、Windows は
    タスクスケジューラとスタートアップ。cron は Unix 系で共通。
    """

    name = "system"
    display = "OS スケジューラ"

    def triggers(self, home: Path, roots: list[Path]) -> Iterator[Trigger]:
        if sys.platform == "darwin":
            yield from self._launchd(home)
        elif sys.platform.startswith("linux"):
            yield from self._systemd(home)
        elif sys.platform == "win32":
            yield from self._windows(home)
        if sys.platform != "win32":
            yield from self._cron()

    def _systemd(self, home: Path) -> Iterator[Trigger]:
        """~/.config/systemd/user/*.timer と *.service を読む。"""
        d = home / ".config" / "systemd" / "user"
        if not d.is_dir():
            return
        for unit in sorted(list(d.glob("*.service")) + list(d.glob("*.timer"))):
            try:
                text = unit.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not _AI_HINT.search(text + " " + unit.name):
                continue
            exec_m = re.search(r"^ExecStart\s*=\s*(.+)$", text, re.MULTILINE)
            on_cal = re.search(r"^OnCalendar\s*=\s*(.+)$", text, re.MULTILINE)
            on_boot = re.search(r"^OnBootSec\s*=\s*(.+)$", text, re.MULTILINE)
            if on_cal:
                event = f"定時 {on_cal.group(1).strip()}"
            elif on_boot:
                event = f"起動 {on_boot.group(1).strip()} 後"
            else:
                event = "systemd ユニット"
            yield Trigger(kind="schedule", event=event, matcher=unit.stem,
                          command=exec_m.group(1).strip() if exec_m else unit.name,
                          source=unit, tool=self.name, scope="user")

    def _windows(self, home: Path) -> Iterator[Trigger]:
        """スタートアップフォルダとタスクスケジューラを見る。"""
        appdata = os.environ.get("APPDATA")
        if appdata:
            startup = (Path(appdata) / "Microsoft" / "Windows" / "Start Menu"
                       / "Programs" / "Startup")
            if startup.is_dir():
                for f in sorted(startup.iterdir()):
                    if _AI_HINT.search(f.name):
                        yield Trigger(kind="schedule", event="ログオン時",
                                      matcher=f.stem, command=str(f),
                                      source=f, tool=self.name, scope="user")
        try:
            out = subprocess.run(["schtasks", "/query", "/fo", "csv", "/nh"],
                                 capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return
        if out.returncode != 0:
            return
        for line in out.stdout.splitlines():
            if not _AI_HINT.search(line):
                continue
            cols = [c.strip('"') for c in line.split('","')]
            if len(cols) < 3:
                continue
            yield Trigger(kind="schedule", event=cols[2] or "タスクスケジューラ",
                          matcher=cols[0], command=cols[0],
                          source=Path("schtasks"), tool=self.name, scope="user")

    def _launchd(self, home: Path) -> Iterator[Trigger]:
        d = home / "Library" / "LaunchAgents"
        if not d.is_dir():
            return
        for plist in sorted(d.glob("*.plist")):
            try:
                with plist.open("rb") as fh:
                    data = plistlib.load(fh)
            except Exception:
                continue
            args = data.get("ProgramArguments") or []
            cmd = " ".join(str(a) for a in args) or str(data.get("Program", ""))
            if not _AI_HINT.search(cmd + " " + str(data.get("Label", ""))):
                continue
            if data.get("StartInterval"):
                event = f"{data['StartInterval']}秒ごと"
            elif data.get("StartCalendarInterval"):
                event = f"定時 {json.dumps(data['StartCalendarInterval'], ensure_ascii=False)}"
            elif data.get("RunAtLoad"):
                event = "ログイン時"
            else:
                event = "launchd"
            yield Trigger(kind="schedule", event=event, matcher=str(data.get("Label", "")),
                          command=cmd, source=plist, tool=self.name, scope="user")

    def _cron(self) -> Iterator[Trigger]:
        try:
            out = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return
        if out.returncode != 0:
            return
        for line in out.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or not _AI_HINT.search(line):
                continue
            parts = line.split(None, 5)
            if len(parts) < 6:
                continue
            yield Trigger(kind="schedule", event=" ".join(parts[:5]), matcher="",
                          command=parts[5], source=Path("crontab"), tool=self.name, scope="user")


ADAPTERS: list[ToolAdapter] = [
    ClaudeCodeAdapter(),
    CodexAdapter(),
    GeminiAdapter(),
    CursorAdapter(),
    CopilotAdapter(),
    OpenCodeAdapter(),
    WindsurfAdapter(),
    ClineAdapter(),
    ZedAdapter(),
    ContinueAdapter(),
    AiderAdapter(),
    AgentsMdAdapter(),
    SystemScheduleAdapter(),
]

# ツール別のホームディレクトリ。容量内訳の集計に使う。
TOOL_HOME_DIRS: list[tuple[str, str]] = [
    (".claude", "Claude Code"),
    (".codex", "Codex CLI"),
    (".gemini", "Gemini CLI"),
    (".cursor", "Cursor"),
    (".copilot", "GitHub Copilot"),
    (".config/opencode", "opencode"),
    (".agents", "AGENTS.md 系"),
    (".hermes", "Hermes"),
    (".continue", "Continue"),
    (".ollama", "Ollama"),
    (".agent-handoff", "セッション引き継ぎ"),
    (".driving-mode", "driving-mode"),
    (".sena", "sena"),
    (".graphify", "graphify"),
    (".hyperresearch", "hyperresearch"),
]
