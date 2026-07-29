"""`python -m ai_env_map` で起動できるようにする。

コマンドの置き場所が PATH に入っていない環境では `ai-env-map` と打っても
見つからない。Python から直接モジュールを呼べば PATH を経由せずに済む。
"""

from .cli import main

raise SystemExit(main())
