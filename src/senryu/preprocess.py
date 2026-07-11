import re

_MENTION_RE = re.compile(r"<@!?\d+>|<@&\d+>|<#\d+>|@everyone|@here")
_URL_RE = re.compile(r"https?://\S+")
_CUSTOM_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")
_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_WHITESPACE_RE = re.compile(r"\s+")


def sanitize_text(raw: str) -> str:
    """Discordメッセージの生テキストから解析の妨げになる要素を除去する。

    コードブロック・インラインコード・メンション(@everyone/@here を含む)・URL・
    カスタム絵文字を除去し、連続する空白を1つの半角スペースに正規化してトリムする。
    """
    text = _CODE_BLOCK_RE.sub(" ", raw)
    text = _INLINE_CODE_RE.sub(" ", text)
    text = _MENTION_RE.sub(" ", text)
    text = _URL_RE.sub(" ", text)
    text = _CUSTOM_EMOJI_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text
