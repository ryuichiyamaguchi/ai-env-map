"""コマンドの入口。特に文字符号化まわりは環境で壊れやすいので固定する。"""

import io
import json
import sys

import pytest

from ai_env_map.cli import main


def test_HTML_を生成して正常終了する(tmp_path, capsys):
    out = tmp_path / "out.html"
    code = main(["--home", str(tmp_path), "-o", str(out), "--no-open", "--fast"])
    assert code == 0
    assert out.is_file()
    assert "<title>" in out.read_text(encoding="utf-8")


def test_出力先の親ディレクトリを作る(tmp_path):
    out = tmp_path / "な" / "い" / "out.html"
    assert main(["--home", str(tmp_path), "-o", str(out), "--no-open", "--fast"]) == 0
    assert out.is_file()


def test_JSON_で出せる(tmp_path, capsys):
    code = main(["--home", str(tmp_path), "--json", "--fast"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert "configs" in data and "tree" in data


def test_共有モードでは本文を埋め込まない(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# 秘密の見出し\n", encoding="utf-8")
    out = tmp_path / "shared.html"
    main(["--home", str(tmp_path), "-o", str(out), "--no-open", "--fast", "--redact"])
    html = out.read_text(encoding="utf-8")
    assert '<script id="filedata" type="application/json">{}</script>' in html


class _NarrowStream(io.TextIOWrapper):
    """日本語を表現できないコンソールの代役。Windows の既定に相当する。"""

    def __init__(self):
        super().__init__(io.BytesIO(), encoding="cp1252", errors="strict")
        self.reconfigured = False

    def reconfigure(self, **kw):
        # 実装が呼んでくれたかどうかを記録し、実際に緩い符号化へ切り替える。
        self.reconfigured = True
        super().reconfigure(**kw)


def test_日本語を出せないコンソールでも落ちない(tmp_path, monkeypatch):
    """Windows の cp1252 コンソールで print が例外を投げないこと。

    成果物を書き終えたあとに標準出力で落ちると、利用者からは失敗に見える。
    """
    stream = _NarrowStream()
    monkeypatch.setattr(sys, "stdout", stream)
    out = tmp_path / "out.html"
    code = main(["--home", str(tmp_path), "-o", str(out), "--no-open", "--fast"])
    assert code == 0
    assert stream.reconfigured, "標準出力の符号化を切り替えていない"
    assert out.is_file()
