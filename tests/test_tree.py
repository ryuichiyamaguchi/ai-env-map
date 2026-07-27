"""ツリー構築と散らかり検出、および生成 HTML の健全性。"""

import json
import re
from html.parser import HTMLParser
from pathlib import Path

from ai_env_map.model import ConfigFile
from ai_env_map.render import render
from ai_env_map.scan import build_tree, detect_issues, scan


def cfg(path: Path, kind="instructions", **kw) -> ConfigFile:
    return ConfigFile(path=path, tool="claude-code", kind=kind,
                      scope=kw.pop("scope", "project"), **kw)


# ---- ツリー -------------------------------------------------------------

def test_設定のある枝だけが残る(tmp_path):
    a = tmp_path / "dev" / "proj"
    a.mkdir(parents=True)
    (tmp_path / "無関係").mkdir()
    tree = build_tree(tmp_path, [cfg(a / "CLAUDE.md")], [])
    names = {n.path.name for n in _walk(tree)}
    assert "proj" in names
    assert "無関係" not in names, "設定のないディレクトリは描かない"


def test_深さが親子で1ずつ増える(tmp_path):
    a = tmp_path / "x" / "y" / "z"
    a.mkdir(parents=True)
    tree = build_tree(tmp_path, [cfg(a / "CLAUDE.md")], [])
    assert tree[0].path == tmp_path and tree[0].depth == 0
    by_name = {n.path.name: n.depth for n in _walk(tree)}
    assert by_name["x"] == 1 and by_name["y"] == 2 and by_name["z"] == 3
    # 子の深さは必ず親 + 1
    for n in _walk(tree):
        for ch in n.children:
            assert ch.depth == n.depth + 1


def test_設定がディレクトリに割り当てられる(tmp_path):
    a = tmp_path / "p"
    a.mkdir()
    c = cfg(a / "CLAUDE.md")
    node = [n for n in _walk(build_tree(tmp_path, [c], [])) if n.path == a][0]
    assert node.configs == [c]


def _walk(nodes):
    for n in nodes:
        yield n
        yield from _walk(n.children)


# ---- 散らかり検出 -------------------------------------------------------

def test_指示ファイルの併存を1件にまとめる(tmp_path):
    d1, d2 = tmp_path / "a", tmp_path / "b"
    for d in (d1, d2):
        d.mkdir()
    configs = [cfg(d / n, lines=n_lines)
               for d in (d1, d2)
               for n, n_lines in (("CLAUDE.md", 100), ("AGENTS.md", 10))]
    issues = detect_issues(tmp_path, configs, [])
    hits = [i for i in issues if i.title == "指示ファイルの併存"]
    assert len(hits) == 1, "箇所ごとに別項目を立てない"
    assert len(hits[0].paths) == 4


def test_同名スキルの重複を見つける(tmp_path):
    configs = [cfg(tmp_path / "a" / "SKILL.md", kind="skill", label="foo"),
               cfg(tmp_path / "b" / "SKILL.md", kind="skill", label="foo")]
    titles = [i.title for i in detect_issues(tmp_path, configs, [])]
    assert "同名スキルの重複" in titles


def test_平文の認証情報を検出項目として出す(tmp_path):
    from ai_env_map.secrets import Secret
    c = cfg(tmp_path / "settings.json", kind="settings")
    c.secrets = [Secret(kind="Google API キー", line=3, hint="AIza…xx（39文字）")]
    issues = detect_issues(tmp_path, [c], [])
    hit = [i for i in issues if i.title == "平文の認証情報"]
    assert hit and hit[0].severity == "high"
    assert "共有しない" in hit[0].detail


def test_散らかりがなければ何も出さない(tmp_path):
    assert detect_issues(tmp_path, [], []) == []


def test_深刻度の高い順に並ぶ(tmp_path):
    configs = [cfg(tmp_path / "a" / "SKILL.md", kind="skill", label="x"),
               cfg(tmp_path / "b" / "SKILL.md", kind="skill", label="x"),
               cfg(tmp_path / "c.md", kind="rules", mtime=1.0)]
    order = {"high": 0, "mid": 1, "low": 2}
    sev = [order[i.severity] for i in detect_issues(tmp_path, configs, [])]
    assert sev == sorted(sev)


# ---- 生成 HTML ----------------------------------------------------------

class _Balance(HTMLParser):
    VOID = {"br", "img", "meta", "link", "input", "hr", "area", "base",
            "col", "embed", "source", "track", "wbr"}

    def __init__(self):
        super().__init__()
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        else:
            self.errors.append(tag)


def test_生成した_HTML_のタグが閉じている(tmp_path):
    html = render(scan(home=tmp_path, skip_sizes=True))
    p = _Balance()
    p.feed(html)
    assert not p.errors and not p.stack, f"{p.errors[:3]} / {p.stack[:3]}"


def test_外部リソースを一切参照しない(tmp_path):
    html = render(scan(home=tmp_path, skip_sizes=True))
    assert not re.findall(r'(?:src|href)="(?:https?:)?//', html)


def test_埋め込み_JSON_が正しく取り出せる(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# 見出し\n本文", encoding="utf-8")
    (tmp_path / ".claude").mkdir()
    html = render(scan(home=tmp_path, skip_sizes=True))
    m = re.search(r'<script id="filedata" type="application/json">(.*?)</script>',
                  html, re.S)
    assert m, "本文データが埋め込まれていない"
    data = json.loads(m.group(1).replace("<\\/", "</"))
    assert any("本文" in v["b"] for v in data.values())


def test_空のホームでも生成できる(tmp_path):
    html = render(scan(home=tmp_path, skip_sizes=True))
    assert "<title>" in html and len(html) > 1000


def test_日本語レイアウト規約が入っている(tmp_path):
    html = render(scan(home=tmp_path, skip_sizes=True))
    assert "word-break:keep-all" in html
    assert "overflow-wrap:break-word" in html


def test_hidden_属性が確実に効く(tmp_path):
    """引き出しの display:flex に負けないよう強制する規則があること。"""
    html = render(scan(home=tmp_path, skip_sizes=True))
    assert "[hidden]{display:none!important}" in html


def test_書式文字列に非ASCIIを使わない():
    """Windows の strftime は書式をロケール符号化に通すため日本語で落ちる。

    「2026-07-28 更新」のような表示は、日付を組んでから連結して作ること。
    """
    import re
    from pathlib import Path as P
    for f in sorted(P("ai_env_map").glob("*.py")):
        for m in re.finditer(r'strftime\(\s*(["\'])(.*?)\1', f.read_text(encoding="utf-8")):
            fmt = m.group(2)
            assert fmt.isascii(), f"{f.name}: strftime の書式に非 ASCII: {fmt!r}"
