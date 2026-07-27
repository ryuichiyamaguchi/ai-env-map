"""共有モードの伏字。ここが壊れると実害が出るので重点的に固定する。"""

from datetime import datetime
from pathlib import Path

from ai_env_map.model import ConfigFile, ScanResult, TreeNode, Trigger
from ai_env_map.render import Renderer, render


def make_result(tmp_home: Path) -> ScanResult:
    secret_dir = tmp_home / "書類" / "acme-corp-hub" / "05_プロジェクトX"
    cfg = ConfigFile(
        path=secret_dir / "CLAUDE.md", tool="claude-code", kind="instructions",
        scope="project", lines=10,
        declares=["acme-corp-hub の開発規約", "プロジェクトX の運用"],
    )
    trig = Trigger(
        kind="hook", event="SessionStart", matcher="acme-corp-hub",
        command=f"node {secret_dir}/scripts/run.js --project acme-corp-hub",
        source=secret_dir / ".claude" / "settings.json",
    )
    node = TreeNode(path=secret_dir, depth=2, configs=[cfg])
    root = TreeNode(path=tmp_home, depth=0, children=[node])
    return ScanResult(
        scanned_at=datetime(2026, 1, 1).strftime("%Y-%m-%d %H:%M"),
        home=tmp_home, roots=[secret_dir], configs=[cfg], triggers=[trig],
        tree=[root],
    )


SECRET_WORDS = ["acme-corp-hub", "プロジェクトX", "05_プロジェクトX"]


def test_共有モードで固有名詞が残らない(tmp_path):
    html = render(make_result(tmp_path), redact=True)
    for w in SECRET_WORDS:
        assert w not in html, f"共有モードなのに漏れた: {w}"


def test_通常モードでは固有名詞が読める(tmp_path):
    html = render(make_result(tmp_path), redact=False)
    assert "acme-corp-hub" in html, "通常モードで実名が消えてはいけない"


def test_コマンド文字列の中のパスも伏せる(tmp_path):
    r = Renderer(make_result(tmp_path), redact=True)
    out = r.text(f"node {tmp_path}/書類/acme-corp-hub/run.js")
    assert "acme-corp-hub" not in out


def test_連番付きフォルダの略称も伏せる(tmp_path):
    """05_プロジェクトX が本文で プロジェクトX と呼ばれても伏せる。"""
    r = Renderer(make_result(tmp_path), redact=True)
    assert "プロジェクトX" not in r.text("プロジェクトX の設定について")


def test_ハイフン区切りのパス名も伏せる(tmp_path):
    """Claude Code は ~/.claude/projects 配下を -Users-name-... と名付ける。"""
    r = Renderer(make_result(tmp_path), redact=True)
    out = r.text("-Users-tanaka-書類-acme-corp-hub-05_プロジェクトX")
    assert "acme-corp-hub" not in out
    assert "tanaka" not in out


def test_同じ語は常に同じ伏字になる(tmp_path):
    r = Renderer(make_result(tmp_path), redact=True)
    assert r.text("acme-corp-hub") == r.text("acme-corp-hub")


def test_共有モードでは本文を埋め込まない(tmp_path):
    """伏字にできない本文は、そもそも共有版に載せない。"""
    res = make_result(tmp_path)
    res.configs[0].content = "秘密の内容 acme-corp-hub"
    res.configs[0].uid = "f0"
    html = render(res, redact=True)
    assert "秘密の内容" not in html


def test_ホームのパスは通常モードでも波線に短縮される(tmp_path):
    r = Renderer(make_result(tmp_path), redact=False)
    assert r.path(tmp_path / "x") == "~/x"
