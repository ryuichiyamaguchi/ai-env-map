# ai-env-map

[![PyPI](https://img.shields.io/pypi/v/ai-env-map)](https://pypi.org/project/ai-env-map/)
[![Python](https://img.shields.io/pypi/pyversions/ai-env-map)](https://pypi.org/project/ai-env-map/)
[![License](https://img.shields.io/pypi/l/ai-env-map)](LICENSE)
[![test](https://github.com/ryuichiyamaguchi/ai-env-map/actions/workflows/test.yml/badge.svg)](https://github.com/ryuichiyamaguchi/ai-env-map/actions/workflows/test.yml)

PC の中に散らばった AI エージェントの設定を、階層構造のまま1枚の HTML にする道具です。

Claude Code、Codex、Gemini CLI、Cursor、Copilot と使うツールが増えるほど、`CLAUDE.md`、
`AGENTS.md`、`settings.json`、`SKILL.md` があちこちの階層に溜まっていきます。どこに何があり、
どれがどれを上書きし、何が自動で動くのかが分からなくなる。それを一覧できるようにします。

- **どの階層に何があるか** — ディレクトリ構造そのままの入れ子ツリー
- **それが何を規定しているか** — 行数ではなく中身。見出し、許可と拒否、フック、モデル指定
- **git の追跡状態** — 追跡されていない設定はその人のマシンにしか効かない
- **何が勝手に動くか** — フック、launchd、systemd、cron、タスクスケジューラ
- **散らかりの検出** — 指示ファイルの併存、同名スキルの重複、平文の認証情報、陳腐化

ネットワーク通信は一切行いません。すべてローカルのファイル読み取りだけで完結します。

## 入れる

### インストール不要で使う（Windows / macOS）

Python も他の道具も入れられない環境向けに、単体で動く実行ファイルを配布しています。
[最新リリース](https://github.com/ryuichiyamaguchi/ai-env-map/releases/latest) から
`ai-env-map-windows.exe` または `ai-env-map-macos` をダウンロードして実行するだけです。

### Python がある場合

```bash
pip install --user ai-env-map
python -m ai_env_map
```

`--user` を付ければ管理者権限は要りません。コマンドの置き場所が PATH に入っていない
環境でも、`python -m ai_env_map` なら PATH を経由せずに起動できます。

### uv や pipx を使う場合

```bash
uv tool install ai-env-map
pipx install ai-env-map
```

Python 3.11 以上が必要です。uv を使う場合は Python 本体も uv が用意します。

## 使う

```bash
ai-env-map
```

`./Deliverables/<日付>/ai-env-map.html` が生成され、ブラウザで開きます。

| オプション | 意味 |
|---|---|
| `-o, --out <パス>` | 出力先を変える |
| `--home <パス>` | 走査の起点。既定はホームディレクトリ |
| `--depth <数>` | プロジェクト探索の深さ上限。既定は 5 |
| `--redact` | 共有モード。後述 |
| `--no-content` | ファイル本文を埋め込まない。出力が軽くなる |
| `--fast` | 容量計測と成果物走査を省く |
| `--json` | HTML ではなく JSON を標準出力に書く |
| `--no-open` | 生成後にブラウザで開かない |

## 出力の読み方

ツリーの各行の `L0` `L1` `L2` が階層の深さです。**深い階層の設定が浅い階層を上書きします**。
同じ名前のファイルが複数の段に現れたら、下の段が勝ちます。

`◧` の付いたファイルはクリックすると中身が右から出てきます。Esc か背景クリックで閉じます。
上部の検索欄と分類チップで絞り込めます。`/` キーで検索欄に移動します。

## 共有するとき

**既定の出力にはファイルの中身がそのまま入ります。** 設定ファイルに API キーが平文で
書かれていれば、それも HTML に入ります。手元で自分の設定を点検するための道具なので
あえて伏せていませんが、その分そのままでは共有できません。

認証情報を検出した場合はページ冒頭に警告帯が出て、何がどのファイルの何行目にあるかを示します。

他の人に渡すときは共有モードを使ってください。

```bash
ai-env-map --redact -o shared.html
```

共有モードでは以下が行われます。

- **ファイル本文を一切埋め込みません**（描画側でも強制されます）
- パス、ディレクトリ名、利用者名を `«a1b2»` のような伏字に置き換えます
- 設定ファイルから抽出した見出しや説明文の中に現れる同じ語も置き換えます
- `05_プロジェクト名` のような連番付きフォルダは、本文中の `プロジェクト名` も置き換えます

ただし**万全ではありません**。ディレクトリ名と一致しない人名・社名・製品名が説明文に
含まれる場合は残ります。外部に出す前に一度目を通してください。

## 対応しているツール

| ツール | 指示 | 設定 | スキル / エージェント | MCP | フック |
|---|---|---|---|---|---|
| Claude Code | ○ | ○ | ○ | ○ | ○ |
| Codex CLI | ○ | ○ | ○ | ○ | ○ |
| Gemini CLI | ○ | ○ | – | ○ | ○ |
| GitHub Copilot | ○ | ○ | ○ | ○ | – |
| opencode | – | ○ | ○ | ○ | – |
| Cursor | ○ | ○ | – | ○ | – |
| Zed | ○ | ○ | – | ○ | – |
| Windsurf | ○ | – | – | – | – |
| Cline | ○ | – | – | – | – |
| Continue | ○ | ○ | – | – | – |
| aider | ○ | ○ | – | – | – |

`AGENTS.md` を読むその他のツールは共通の受け皿で拾います。

## 対応ツールを増やす

`ai_env_map/adapters.py` に `ToolAdapter` のサブクラスを1つ足し、`ADAPTERS` に登録する
だけです。走査側と描画側は変更しません。

```python
class MyToolAdapter(ToolAdapter):
    name = "mytool"
    display = "My Tool"
    project_markers = (".mytoolrules",)

    def global_configs(self, home):
        f = home / ".mytool" / "config.json"
        if f.is_file():
            yield _cfg(f, self.name, "settings", "user")
```

各メソッドは実装しなくても構いません。例外を投げても走査全体は止まらず、
そのアダプタの結果だけが欠けて走査ログに記録されます。

## 動作環境

Python 3.11 以上。macOS、Linux、Windows。依存パッケージはありません。

OS ごとに見る場所が変わります。macOS は launchd、Linux は systemd のユーザーユニット、
Windows はタスクスケジューラとスタートアップフォルダを読みます。

## 開発

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python pytest
.venv/bin/python -m pytest tests/ -q
```

伏字と認証情報の検出はテストで固定してあります。ここを変更するときは必ずテストも
確認してください。壊れると実害が出ます。

CI では macOS・Linux・Windows の3つで Python 3.11 と 3.13 を回し、実際に走査して
HTML が生成できること、生成物に外部参照が混入していないことまで確認しています。

## ライセンス

MIT
