"""実行ファイルを作るときの入口。

PyInstaller は指定したスクリプトを最上位モジュールとして扱うため、
ai_env_map/__main__.py をそのまま渡すと `from .cli import main` の
相対 import が「親パッケージがない」として失敗する。
絶対 import で呼ぶだけの薄い入口をここに置く。
"""

from ai_env_map.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
