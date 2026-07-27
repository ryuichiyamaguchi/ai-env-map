"""アダプタの解析部。壊れた入力で落ちないことを最優先で確かめる。

各ツールの設定形式は頻繁に変わる。ここが例外を投げると走査全体が止まるので、
壊れた入力・欠けた鍵・想定外の型のすべてで「静かに空を返す」ことを固定する。
"""

import json

import pytest

from ai_env_map.adapters import (
    ClaudeCodeAdapter, CodexAdapter, GeminiAdapter, parse_claude_style_hooks,
    _read_json, _read_toml, _hook_command,
)
from ai_env_map.inspect import inspect_config, inspect_settings, _front_matter


# ---- 壊れた入力 ---------------------------------------------------------

@pytest.mark.parametrize("body", [
    "",                                   # 空
    "{",                                  # 途中で切れた JSON
    "not json at all",                    # そもそも JSON でない
    '{"hooks": "文字列であって配列ではない"}',
    '{"hooks": {"SessionStart": "配列ではない"}}',
    '{"hooks": {"SessionStart": [null, 3, "x"]}}',
    '{"hooks": null}',
    '[]',                                 # 配列が来た
])
def test_壊れた設定でフック解析が落ちない(tmp_path, body):
    f = tmp_path / "settings.json"
    f.write_text(body, encoding="utf-8")
    assert list(parse_claude_style_hooks(f, "claude-code", "user")) == []


def test_行コメント付き_JSON_を読める(tmp_path):
    f = tmp_path / "settings.json"
    f.write_text('{\n  // 説明\n  "model": "opus",\n}', encoding="utf-8")
    assert _read_json(f) == {"model": "opus"}


def test_壊れた_TOML_は_None(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text("これは [ TOML ではない", encoding="utf-8")
    assert _read_toml(f) is None


def test_存在しないファイルで落ちない(tmp_path):
    assert _read_json(tmp_path / "ない.json") is None
    assert _read_toml(tmp_path / "ない.toml") is None


# ---- フックの中身 -------------------------------------------------------

def test_args_を連結してコマンドの実体を出す():
    spec = {"type": "command", "command": "/bin/bash",
            "args": ["-lc", "echo hi"]}
    assert _hook_command(spec) == "/bin/bash -lc echo hi"


def test_args_がなければ_command_のみ():
    assert _hook_command({"command": "/usr/bin/true"}) == "/usr/bin/true"


def test_フックを正しく取り出す(tmp_path):
    f = tmp_path / "settings.json"
    f.write_text(json.dumps({"hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "guard.sh"}]}
    ]}}), encoding="utf-8")
    got = list(parse_claude_style_hooks(f, "claude-code", "user"))
    assert len(got) == 1
    assert got[0].event == "PreToolUse"
    assert got[0].matcher == "Bash"
    assert got[0].command == "guard.sh"


def test_Codex_の_config_toml_の_hooks_はイベントではない(tmp_path):
    """[hooks] は承認済みハッシュの保管場所。イベントとして数えない。"""
    codex = tmp_path / ".codex"
    codex.mkdir()
    (codex / "config.toml").write_text(
        '[hooks.state]\n"a:b:0:0" = { trusted_hash = "sha256:xxx" }\n',
        encoding="utf-8")
    events = [t.event for t in CodexAdapter().triggers(tmp_path, [])]
    assert "state" not in events


def test_Codex_は_hooks_json_からフックを読む(tmp_path):
    codex = tmp_path / ".codex"
    codex.mkdir()
    (codex / "hooks.json").write_text(json.dumps({"hooks": {"SessionStart": [
        {"hooks": [{"type": "command", "command": "session.js"}]}]}}),
        encoding="utf-8")
    events = [t.event for t in CodexAdapter().triggers(tmp_path, [])]
    assert events == ["SessionStart"]


# ---- 設定の読み取り -----------------------------------------------------

def test_settings_から規定内容を取り出す(tmp_path):
    f = tmp_path / "settings.json"
    f.write_text(json.dumps({
        "permissions": {"allow": ["Bash(ls)"], "deny": ["Read(~/.ssh/**)"],
                        "defaultMode": "auto"},
        "env": {"FOO": "1"},
        "model": "opus",
        "hooks": {"Stop": [{"hooks": [{"command": "x"}]}]},
    }), encoding="utf-8")
    declares, stats = inspect_settings(f)
    assert stats["許可"] == 1 and stats["拒否"] == 1
    assert stats["環境変数"] == 1 and stats["フック"] == 1
    assert any("既定モード auto" in d for d in declares)
    assert any("モデル opus" in d for d in declares)


def test_空の設定でも壊れない(tmp_path):
    f = tmp_path / "settings.json"
    f.write_text("{}", encoding="utf-8")
    declares, stats = inspect_settings(f)
    assert declares and stats == {}


# ---- フロントマター -----------------------------------------------------

def test_フロントマターを読む():
    meta, body = _front_matter("---\nname: x\ndescription: 説明\n---\n本文\n")
    assert meta["name"] == "x"
    assert meta["description"] == "説明"
    assert body.strip() == "本文"


def test_複数行のフロントマターをつなげる():
    meta, _ = _front_matter("---\ndescription: >-\n  一行目\n  二行目\n---\n")
    assert "一行目" in meta["description"] and "二行目" in meta["description"]


def test_フロントマターがなければそのまま返す():
    meta, body = _front_matter("# 見出し\n本文")
    assert meta == {}
    assert body.startswith("# 見出し")


def test_閉じていないフロントマターで落ちない():
    meta, body = _front_matter("---\nname: x\n本文だけ続く")
    assert meta == {}


def test_指示ファイルの見出しを規定内容として取り出す(tmp_path):
    f = tmp_path / "CLAUDE.md"
    f.write_text("# 方針\n\n## 委譲の基準\n\n### 詳細\n\n- IMPORTANT: 必ず守る\n",
                 encoding="utf-8")
    headings, stats = inspect_config(f, "instructions")
    assert headings == ["方針", "委譲の基準", "詳細"]
    assert stats["見出し"] == 3
    assert stats["強調指示"] >= 1


def test_未知の種別でも例外を投げない(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"\x00\x01\x02")
    assert inspect_config(f, "未知") == ([], {})


# ---- アダプタの全体挙動 -------------------------------------------------

@pytest.mark.parametrize("adapter", [ClaudeCodeAdapter(), CodexAdapter(),
                                     GeminiAdapter()])
def test_空のホームで何も返さず落ちない(tmp_path, adapter):
    assert list(adapter.global_configs(tmp_path)) == []
    assert list(adapter.triggers(tmp_path, [])) == []
    assert list(adapter.mcp_servers(tmp_path, [])) == []
    assert list(adapter.project_configs(tmp_path)) == []
