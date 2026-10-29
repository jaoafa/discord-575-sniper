from .chain import chain_ineligibility_reason
from .finder import (
    DEFAULT_PATTERNS,
    MIN_SCORE,
    can_start_part,
    find_candidates,
    has_substantive_mora,
    has_unknown_mora_word,
    pick_best,
    score_candidate,
)
from .mora import total_mora
from .preprocess import sanitize_text
from .tokenizer import Morpheme, tokenize

DISCORD_MESSAGE_LIMIT = 2000

_MAX_MORPHEME_ROWS = 40
_MAX_REJECTED_SPLITS = 5
# フィルタなしの列挙では、ゼロモーラの記号が連続すると分割の候補数が指数的に増える。
# 公開コマンドの入力でも探索が終わるよう、再帰の呼び出し回数に上限を設ける。
_MAX_SEARCH_STEPS = 20000
_TRUNCATE_AT = 1990

Split = list[tuple[int, int]]


def _escape(text: str) -> str:
    """ユーザー由来の文字列がコードブロックを壊さないよう、バッククォートを全角にする。"""
    return text.replace("`", "｀")


def _cell(text: str) -> str:
    """形態素表の1セル用に、バッククォートを全角にし、改行を `\\n` の2文字にする。"""
    return _escape(text).replace("\n", "\\n")


def _truncate(message: str) -> str:
    """Discord のメッセージ上限を超える場合に切り詰め、開いたままのコードフェンスを閉じる。"""
    if len(message) <= DISCORD_MESSAGE_LIMIT:
        return message
    cut = message[:_TRUNCATE_AT] + "…"
    if cut.count("```") % 2:
        cut += "\n```"
    return cut


def _enumerate_splits(
    morphemes: list[Morpheme], pattern: tuple[int, ...], budget: list[int]
) -> list[Split]:
    """モーラ数だけで pattern に分割できる位置をすべて列挙する(棄却理由を問わない)。

    探索規則は finder._find_from と同じ(全開始位置、最後以外のパートが末尾に達する分割の除外、
    ゼロモーラ形態素による終端の複数化)で、句の先頭の付属語などによる枝刈りだけを行わない。
    budget[0] を探索のたびに減らし、負になったら打ち切る。
    """
    n = len(morphemes)
    prefix = [0] * (n + 1)
    for idx, m in enumerate(morphemes):
        prefix[idx + 1] = prefix[idx] + m.mora
    splits: list[Split] = []

    def walk(bounds: list[int], remaining: tuple[int, ...]) -> None:
        budget[0] -= 1
        if budget[0] < 0:
            return
        if not remaining:
            splits.append(list(zip(bounds, bounds[1:])))
            return
        start = bounds[-1]
        target = remaining[0]
        is_last_part = len(remaining) == 1
        for end in range(start + 1, n + 1):
            s = prefix[end] - prefix[start]
            if s < target:
                continue
            if s > target:
                break
            if not is_last_part and end >= n:
                continue
            walk(bounds + [end], remaining[1:])

    for i in range(n):
        walk([i], pattern)
    return splits


def _rejection_reason(morphemes: list[Morpheme], ranges: Split) -> str | None:
    """分割が find_candidates / pick_best で採用されない理由を、判定順で最初の1件だけ返す。"""
    for number, (s, _) in enumerate(ranges, start=1):
        if not can_start_part(morphemes[s]):
            return f"第{number}句の先頭が付属語です(品詞: {morphemes[s].pos})"
    if has_unknown_mora_word(morphemes[ranges[0][0]:ranges[-1][1]]):
        return "記号・空白以外で読みが取れない語(未知語)を含みます"
    if not all(has_substantive_mora(morphemes[s:e]) for s, e in ranges):
        return "促音(ッ)だけで構成された句があります"
    score, _ = score_candidate(morphemes, ranges)
    if score < MIN_SCORE:
        return f"スコア不足です(score={score:.2f} < MIN_SCORE={MIN_SCORE:.2f})"
    return None


def _part_texts(morphemes: list[Morpheme], ranges: Split) -> list[str]:
    """各パートの表層文字列を、記号・空白(mora=0)を除いて連結して返す。"""
    return [
        "".join(m.surface for m in morphemes[s:e] if m.mora > 0) for s, e in ranges
    ]


def _explain_morphemes(morphemes: list[Morpheme]) -> str:
    """形態素ごとの表層・読み・モーラ数・品詞を表にまとめる。"""
    header = f"**形態素解析**(総モーラ数: {total_mora(morphemes)})"
    if not morphemes:
        return f"{header}\n(形態素なし)"
    rows = [
        f"{_cell(m.surface)} | {_cell(m.reading)} | {m.mora} | {m.pos}"
        for m in morphemes[:_MAX_MORPHEME_ROWS]
    ]
    if len(morphemes) > _MAX_MORPHEME_ROWS:
        rows.append(f"…ほか {len(morphemes) - _MAX_MORPHEME_ROWS} 件")
    return f"{header}\n```\n表層 | 読み | モーラ | 品詞\n" + "\n".join(rows) + "\n```"


def _explain_detection(text: str, morphemes: list[Morpheme]) -> str:
    """単一メッセージ内検出の結果と、検出されない場合の棄却理由を説明する。"""
    best = pick_best(find_candidates(morphemes, text))
    if best is not None:
        lines = "\n".join(f"> {_escape(p)}" for p in best.parts)
        return f"**単一メッセージ内検出**: 検出されます\n{lines}\nスコア: {best.score:.2f}"

    head = "**単一メッセージ内検出**: 検出されません"
    budget = [_MAX_SEARCH_STEPS]
    found: list[tuple[int, Split]] = []
    for pattern_idx, pattern in enumerate(DEFAULT_PATTERNS):
        found.extend((pattern_idx, ranges) for ranges in _enumerate_splits(morphemes, pattern, budget))
    if not found:
        if total_mora(morphemes) < sum(DEFAULT_PATTERNS[0]):
            return f"{head}\n5-7-5 にも 5-7-5-7-7 にも分割できません(モーラ数不足)"
        return f"{head}\n5-7-5 にも 5-7-5-7-7 にも分割できません(形態素の区切りでは音数が合いません)"

    found.sort(key=lambda f: (f[0], f[1][0][0], f[1][-1][1], f[1]))
    lines = []
    for pattern_idx, ranges in found[:_MAX_REJECTED_SPLITS]:
        reason = _rejection_reason(morphemes, ranges)
        assert reason is not None, (
            f"検出されないのに棄却理由の無い分割があります: ranges={ranges}, text={text!r}"
        )
        pattern_label = "-".join(str(n) for n in DEFAULT_PATTERNS[pattern_idx])
        parts = " / ".join(_escape(p) for p in _part_texts(morphemes, ranges))
        lines.append(f"- {pattern_label}: {parts} … {reason}")
    if len(found) > _MAX_REJECTED_SPLITS:
        lines.append(f"- ほか {len(found) - _MAX_REJECTED_SPLITS} 件")
    if budget[0] < 0:
        lines.append("- 候補が多いため、探索を途中で打ち切りました")
    return f"{head}\n棄却された分割:\n" + "\n".join(lines)


def _explain_chain(morphemes: list[Morpheme]) -> str:
    """メッセージ単体が連歌チェーンに加われるかを説明する。"""
    reason = chain_ineligibility_reason(morphemes)
    if reason is None:
        verdict = f"このメッセージ単体はチェーンに加われます(総モーラ数: {total_mora(morphemes)})"
    else:
        verdict = f"加われません — {reason}"
    return f"**連歌チェーン**: {verdict}\n※ チャンネルのチェーンの実際の状態(直前のメッセージ)は反映しません。"


def build_explanation(text: str, morphemes: list[Morpheme]) -> str:
    """サニタイズ済みテキストとその形態素列から、検出可否と棄却理由の説明文を組み立てる。

    Args:
        text: サニタイズ済みのテキスト。
        morphemes: text を形態素解析した結果。空リストも受け付ける。

    Returns:
        Discord に送れる(2000文字以内の)説明文。
    """
    shown_text = _escape(text) if text else "サニタイズ後のテキストが空です"
    sections = [
        f"**サニタイズ後**\n```\n{shown_text}\n```",
        _explain_morphemes(morphemes),
        _explain_detection(text, morphemes),
        _explain_chain(morphemes),
    ]
    return _truncate("\n\n".join(sections))


def explain_text(raw_text: str) -> str:
    """Discord の生テキストを検出パイプラインと同じ手順で解析し、説明文を返す。"""
    text = sanitize_text(raw_text)
    morphemes = tokenize(text) if text else []
    return build_explanation(text, morphemes)
