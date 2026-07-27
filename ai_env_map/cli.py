"""コマンドライン入口。"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from datetime import date
from pathlib import Path

from .render import render
from .scan import scan


def _default_out() -> Path:
    return Path.cwd() / "Deliverables" / date.today().isoformat() / "ai-env-map.html"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="ai-env-map",
        description="この PC の AI エージェント設定・成果物・自動発火を棚卸しして HTML にする",
    )
    ap.add_argument("--home", type=Path, default=None,
                    help="走査の起点。既定はホームディレクトリ")
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="出力先 HTML。既定は ./Deliverables/<日付>/ai-env-map.html")
    ap.add_argument("--depth", type=int, default=5, help="プロジェクト探索の深さ上限")
    ap.add_argument("--redact", action="store_true",
                    help="共有モード。個人を特定しうるディレクトリ名を伏せる")
    ap.add_argument("--json", dest="as_json", action="store_true",
                    help="HTML ではなく JSON を標準出力に書く")
    ap.add_argument("--fast", action="store_true",
                    help="容量計測と成果物走査を省いて高速に済ませる")
    ap.add_argument("--no-content", action="store_true",
                    help="ファイル本文を埋め込まない。出力が軽くなる代わりに"
                         "クリックでの中身表示ができなくなる")
    ap.add_argument("--no-open", action="store_true", help="生成後にブラウザで開かない")
    args = ap.parse_args(argv)

    # 共有モードでは本文を埋め込まない。パスを伏せても本文が丸ごと
    # 入っていては共有できないため、既定で落とす。
    skip_content = args.no_content or args.redact
    result = scan(home=args.home, max_depth=args.depth,
                  skip_sizes=args.fast, skip_content=skip_content)

    if args.as_json:
        json.dump(result.to_json(), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    out = args.out or _default_out()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(result, redact=args.redact), encoding="utf-8")

    print(f"出力    : {out}")
    print(f"対象    : プロジェクト {len(result.projects)} 件 / "
          f"設定 {len(result.configs)} 件 / トリガー {len(result.triggers)} 件 / "
          f"MCP {len(result.mcp_servers)} 件")
    if result.violations:
        print(f"要確認  : 直置きファイル {len(result.violations)} 件")
    if not args.no_open:
        webbrowser.open(out.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
