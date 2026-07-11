from src.senryu.preprocess import sanitize_text


def test_removes_user_mention():
    """ユーザーメンション表記が除去されることを確認する。"""
    assert sanitize_text("<@123456789> こんにちは") == "こんにちは"


def test_removes_role_mention():
    """ロールメンション表記が除去されることを確認する。"""
    assert sanitize_text("<@&987654321> 会議です") == "会議です"


def test_removes_channel_mention():
    """チャンネルメンション表記が除去されることを確認する。"""
    assert sanitize_text("<#111222333> を見て") == "を見て"


def test_removes_url():
    """URL 部分が除去されることを確認する。"""
    assert sanitize_text("見て https://example.com/path?q=1 ください") == "見て ください"


def test_removes_custom_emoji():
    """カスタム絵文字表記が除去されることを確認する。"""
    assert sanitize_text("やったね <:kawaii:123456789012345678>") == "やったね"


def test_removes_code_block():
    """コードブロックが除去されることを確認する。"""
    assert sanitize_text("説明です ```print(1)``` 以上") == "説明です 以上"


def test_removes_inline_code():
    """インラインコードが除去されることを確認する。"""
    assert sanitize_text("これは `code` です") == "これは です"


def test_normalizes_whitespace():
    """改行や連続する空白が単一の半角スペースに正規化されることを確認する。"""
    assert sanitize_text("古池や\n\n蛙飛び込む   水の音") == "古池や 蛙飛び込む 水の音"


def test_empty_after_sanitize():
    """サニタイズ対象のみの入力が空文字列になることを確認する。"""
    assert sanitize_text("<@123456789>") == ""


def test_removes_everyone_mention():
    """プレーンテキストの @everyone が除去されることを確認する
    (メンション注入対策。<@!?\\d+> 等の構造化メンションとは別扱い)。
    """
    assert sanitize_text("@everyone 集合です") == "集合です"


def test_removes_here_mention():
    """プレーンテキストの @here が除去されることを確認する。"""
    assert sanitize_text("@here 見てください") == "見てください"
