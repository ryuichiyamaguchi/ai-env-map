"""設定ファイルに平文で置かれた認証情報を見つける。

隠すためではなく、知らせるための機能。設定の衛生状態としてこの道具が
報告すべき項目であり、本文の表示は加工しない。手元で自分の設定を点検する
のに、自分の鍵が伏せられていては用をなさないため。

出力 HTML を共有する経路は別で塞いである（共有モードは本文を埋め込まない）。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

# 形が特定できるもの。誤検出が少ないのでそのまま報告してよい。
SIGNATURES: list[tuple[str, re.Pattern]] = [
    ("Anthropic API キー", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("OpenAI API キー", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}")),
    ("Google API キー", re.compile(r"\bAIza[A-Za-z0-9_\-]{35}\b")),
    ("GitHub トークン", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("GitLab トークン", re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}\b")),
    ("Slack トークン", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("AWS アクセスキー", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Stripe 秘密鍵", re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{20,}\b")),
    ("Hugging Face トークン", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    ("秘密鍵ファイルの中身", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("JSON Web Token", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.")),
]

# 形では判断できないもの。キー名で当たりを付けてから中身の乱雑さで絞る。
ASSIGNMENT = re.compile(
    r"""(?ix)
    ["']?(?P<name>[A-Za-z0-9_.\-]*
        (?:api[_\-]?key|secret|token|password|passwd|credential|private[_\-]?key)
     [A-Za-z0-9_.\-]*)["']?
    \s*[:=]\s*
    ["'](?P<value>[^"'\s]{16,})["']
    """
)

# 値そのものではなく参照や空欄を指しているとき。報告しない。
PLACEHOLDER = re.compile(
    r"(?i)^(?:\$\{?[a-z_]|%[a-z_]+%|<[^>]+>|your[_\-]|xxx|dummy|example|sample|"
    r"changeme|placeholder|todo|none|null|true|false|\.\.\.)"
)

# 参照だけで実体を持たない書き方。環境変数の展開など。
REFERENCE = re.compile(r"\$\{[^}]+\}|\$[A-Z_][A-Z0-9_]*|%[A-Za-z_]+%")


def shannon_entropy(s: str) -> float:
    """1文字あたりの情報量。ランダムな鍵は高く、英単語や文章は低い。"""
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


@dataclass
class Secret:
    kind: str          # 検出した種類の名前
    line: int          # 1 始まりの行番号
    hint: str          # 値そのものではなく、先頭数文字だけの手掛かり
    name: str = ""     # 代入先のキー名（分かる場合）


def _hint(value: str) -> str:
    """値の全体は返さない。同定できる程度の断片だけ返す。"""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}…{value[-2:]}（{len(value)}文字）"


def scan_text(text: str, limit: int = 20) -> list[Secret]:
    """本文から認証情報らしき箇所を拾う。"""
    found: list[Secret] = []
    seen: set[tuple[str, int]] = set()

    for lineno, line in enumerate(text.splitlines(), 1):
        if len(line) > 4000:      # 圧縮済みファイルなどは対象外
            continue
        matched_here = False
        for kind, pat in SIGNATURES:
            m = pat.search(line)
            if not m:
                continue
            key = (kind, lineno)
            if key in seen:
                continue
            seen.add(key)
            matched_here = True
            found.append(Secret(kind=kind, line=lineno, hint=_hint(m.group(0))))
            if len(found) >= limit:
                return found
        # 形で特定できた行を、汎用の代入検出で二重に数えない。
        if matched_here:
            continue

        for m in ASSIGNMENT.finditer(line):
            value = m.group("value")
            if PLACEHOLDER.match(value) or REFERENCE.search(value):
                continue
            # 素性の分からない値は、乱雑さが一定以上のときだけ疑う。
            if shannon_entropy(value) < 3.4:
                continue
            key = ("代入", lineno)
            if key in seen:
                continue
            seen.add(key)
            found.append(Secret(kind="認証情報らしき値", line=lineno,
                                hint=_hint(value), name=m.group("name")))
            if len(found) >= limit:
                return found
    return found


# 中身が認証情報そのものである可能性が高く、既定では本文を読まないファイル。
# 走査対象の設定ファイルには通常含まれないが、将来の拡張に備えて持つ。
SENSITIVE_NAMES = {
    ".env", ".env.local", ".env.production", ".netrc", "credentials",
    "id_rsa", "id_ed25519", ".npmrc", ".pypirc",
}


def is_sensitive_file(path: Path) -> bool:
    return path.name in SENSITIVE_NAMES or path.name.startswith(".env.")
