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
    カスタム絵文字を除去し、連続する空白を正規化してトリムする(改行を含む連続は \n 1つ、
    それ以外は半角スペース1つ)。
    """
    text = _CODE_BLOCK_RE.sub(" ", raw)
    text = _INLINE_CODE_RE.sub(" ", text)
    text = _MENTION_RE.sub(" ", text)
    text = _URL_RE.sub(" ", text)
    text = _CUSTOM_EMOJI_RE.sub(" ", text)
    # 改行は句の切れ目の手掛かりになるため、改行を含む空白の連続は \n 1つに正規化して残す。
    text = _WHITESPACE_RE.sub(lambda m: "\n" if re.search(r"[\r\n]", m.group()) else " ", text).strip()
    return text
