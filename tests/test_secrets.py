"""認証情報の検出。見逃しよりも誤検出のほうが体験を壊すので両方を固定する。"""

from ai_env_map.secrets import scan_text, shannon_entropy


def fake(*parts: str) -> str:
    """鍵の形をした文字列を実行時に組み立てる。

    値そのものはすべて架空だが、リポジトリ上に鍵らしき literal を残すと
    GitHub の秘密情報スキャンに拾われて push が拒否される。テストの意図は
    「本物と同じ形を検出できること」なので、組み立て後の値は本物と同形にする。
    """
    return "".join(parts)


ANTHROPIC = fake("sk-", "ant-", "api03-AbCdEfGhIjKlMnOpQrStUvWxYz012345")
GOOGLE = fake("AIza", "SyD1234567890abcdefghijklmnopqrstuv")
GITHUB = fake("ghp", "_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
AWS = fake("AKIA", "IOSFODNN7EXAMPLE")
SLACK = fake("xoxb", "-123456789012-abcdefghijklmno")
PRIVATE_KEY = fake("-----BEGIN ", "RSA PRIVATE KEY-----")


def kinds(text):
    return {s.kind for s in scan_text(text)}


def test_署名で特定できる鍵を見つける():
    cases = [
        (ANTHROPIC, "Anthropic API キー"),
        (GOOGLE, "Google API キー"),
        (GITHUB, "GitHub トークン"),
        (AWS, "AWS アクセスキー"),
        (SLACK, "Slack トークン"),
    ]
    for value, expected in cases:
        assert expected in kinds(f'k = "{value}"'), f"見逃した: {expected}"
    assert "秘密鍵ファイルの中身" in kinds(PRIVATE_KEY)


def test_値そのものは返さない():
    found = scan_text(f'{{"apiKey": "{GOOGLE}"}}')
    assert found
    for s in found:
        assert GOOGLE not in s.hint, "手掛かりに値の全体が含まれてはいけない"
        assert s.hint.startswith(GOOGLE[:4])


def test_環境変数の参照は認証情報ではない():
    for text in ('{"token": "${GITHUB_TOKEN}"}',
                 '{"apiKey": "$ANTHROPIC_API_KEY"}',
                 'token = "%USERPROFILE%_something_long"'):
        assert not scan_text(text), f"参照を誤検出した: {text}"


def test_プレースホルダは認証情報ではない():
    for text in ('{"password": "your-password-here"}',
                 '{"secret": "changeme_please_now_ok"}',
                 '{"apiKey": "<YOUR_API_KEY_GOES_HERE>"}',
                 '{"token": "example-token-value-here"}'):
        assert not scan_text(text), f"プレースホルダを誤検出した: {text}"


def test_普通の設定値は認証情報ではない():
    text = """{
      "model": "claude-opus-5-20260101",
      "outputStyle": "default explanatory style",
      "statusLine": "sh ~/.claude/hud/custom-statusline.mjs",
      "description": "this is a normal sentence and should not match"
    }"""
    assert not scan_text(text)


def test_同じ行を二重に数えない():
    found = scan_text(f'{{"apiKey": "{GOOGLE}"}}')
    assert len(found) == 1, f"二重に検出した: {[s.kind for s in found]}"


def test_乱雑さの判定():
    assert shannon_entropy("aB3xK9mQ7pL2vR5tY8wZ4nC6hJ1sD0fG") > 4.0
    assert shannon_entropy("aaaaaaaaaaaaaaaa") < 1.0
    assert shannon_entropy("") == 0.0


def test_乱雑さの低い値は認証情報とみなさない():
    assert not scan_text('{"secret": "aaaaaaaaaaaaaaaaaaaa"}')


def test_件数の上限が効く():
    text = "\n".join(f'key{i} = "{GITHUB}{i}"' for i in range(50))
    assert len(scan_text(text, limit=5)) == 5


def test_空文字と巨大な一行で落ちない():
    assert scan_text("") == []
    assert scan_text("x" * 100_000) == []
