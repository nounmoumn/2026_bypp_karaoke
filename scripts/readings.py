"""Korean-reading (한글 독음) timing, derived from the aligned Japanese characters.

The aligner times Japanese display characters. This module turns those into
per-mora times (a kanji's span is split over the moras of its reading), then
either
  * aligns a provided Korean reading to that mora timeline (DP over romaji,
    tolerant to spelling variants such as 쇼오/쇼, 난쥿/난주), or
  * generates a Korean reading from the kana when none was provided, in which
    case every Korean syllable inherits its moras' times by construction.
"""

import re
import unicodedata

import pykakasi

_kks = pykakasi.kakasi()

SMALL = set("ゃゅょぁぃぅぇぉゎ")
SPACE_PUNCT = set(" 　,.!?！？、。・～~「」『』()（）…")


def kata_to_hira(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def split_moras(hira: str) -> list[str]:
    out = []
    for ch in hira:
        if ch in SMALL and out and out[-1] not in ("っ", "ん", "ー"):
            out[-1] += ch
        elif "ぁ" <= ch <= "ゖ" or ch == "ー":
            out.append(ch)
    return out


# ---------------------------------------------------------------- Japanese side
def jp_moras(chars: list[dict]) -> list[dict]:
    """[{m: mora (hiragana), s, e}] for one line, from display chars with timing."""
    text = "".join(c["c"] for c in chars)
    # carry timing into untimed chars so every mora has a span
    last = next((c["s"] for c in chars if c["s"] is not None), 0.0)
    timed = []
    for c in chars:
        s, e = (c["s"], c["e"]) if c["s"] is not None else (last, last)
        timed.append((s, e)); last = e
    out, pos = [], 0
    for tok in _kks.convert(text):
        orig, hira = tok["orig"], kata_to_hira(tok["hira"])
        span = list(range(pos, pos + len(orig))); pos += len(orig)
        if not span:
            continue
        oh = kata_to_hira(orig)
        if all(("ぁ" <= ch <= "ゖ") or ch == "ー" for ch in oh):  # kana token: each mora keeps its own chars' times
            k = 0
            for m in split_moras(oh):
                idx = span[k:k + len(m)]; k += len(m)
                out.append({"m": m, "s": timed[idx[0]][0], "e": timed[idx[-1]][1]})
            continue
        if not any("一" <= ch <= "鿿" or "々" == ch for ch in orig):
            continue  # punctuation / latin / spaces: no moras
        # kanji token with okurigana: peel matching kana at both ends, split the kanji core evenly
        pre = 0
        while pre < len(oh) and pre < len(hira) and oh[pre] == hira[pre] and not ("一" <= orig[pre] <= "鿿"):
            pre += 1
        suf = 0
        while (suf < len(oh) - pre and suf < len(hira) - pre and oh[-1 - suf] == hira[-1 - suf]
               and not ("一" <= orig[-1 - suf] <= "鿿")):
            suf += 1
        for j in range(pre):
            out.append({"m": oh[j], "s": timed[span[j]][0], "e": timed[span[j]][1]})
        core_idx = span[pre:len(span) - suf]
        core_m = split_moras(hira[pre:len(hira) - suf])
        if core_idx and core_m:
            s0, e0 = timed[core_idx[0]][0], timed[core_idx[-1]][1]
            for j, m in enumerate(core_m):
                out.append({"m": m, "s": s0 + (e0 - s0) * j / len(core_m), "e": s0 + (e0 - s0) * (j + 1) / len(core_m)})
        for j in range(len(span) - suf, len(span)):
            out.append({"m": oh[j], "s": timed[span[j]][0], "e": timed[span[j]][1]})
    return out


def mora_romaji(m: str) -> str:
    if m == "っ": return "Q"
    if m == "ん": return "N"
    if m == "ー": return "-"
    r = _kks.convert(m)[0]["hepburn"]
    return r or m


# ---------------------------------------------------------------- Korean side
CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
JONG = ["", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"]
C_ROM = dict(zip(CHO, ["k", "k", "n", "d", "t", "r", "m", "b", "p", "s", "s", "", "j", "ts", "ch", "k", "t", "p", "h"]))
V_ROM = dict(zip(JUNG, ["a", "e", "ya", "ye", "o", "e", "yo", "ye", "o", "wa", "we", "we", "yo", "u", "wo", "we", "wi", "yu", "u", "i", "i"]))


def hangul_tokens(syl: str) -> list[str]:
    """One Korean syllable -> mora-like romaji tokens (CV, plus Q/N for a final)."""
    code = ord(syl) - 0xAC00
    if not 0 <= code < 11172:
        return ["-"] if syl in "-ー~" else []
    cho, jung, jong = code // 588, (code % 588) // 28, code % 28
    toks = [C_ROM[CHO[cho]] + V_ROM[JUNG[jung]]]
    f = JONG[jong]
    if f in ("ㄴ", "ㅇ", "ㅁ"):
        toks.append("N")
    elif f:
        toks.append("Q")
    return toks


def _sim(a: str, b: str) -> float:
    """Substitution cost between a Korean-derived token and a Japanese mora (romaji)."""
    if a == b: return 0.0
    if a in "QN-" or b in "QN-":
        if a == "-" and b[-1:] in "aiueo" and len(b) == 1: return 0.2  # 쿄- vs きょう
        if b == "-" and a[-1:] in "aiueo" and len(a) == 1: return 0.2
        return 1.0
    va, vb = a[-1], b[-1]
    ca, cb = a[:-1], b[:-1]
    norm = {"j": "z", "ch": "t", "ts": "t", "sh": "s", "sy": "s", "chy": "t", "f": "h", "d": "t", "g": "k", "b": "p", "z": "s"}
    ca2, cb2 = norm.get(ca, ca), norm.get(cb, cb)
    if va == vb and ca2 == cb2: return 0.15
    if va == vb: return 0.45
    if ca2 == cb2: return 0.6
    return 1.0


def align_reading(chars: list[dict], reading: str) -> list[dict]:
    """Give each character of a provided Korean reading a time span."""
    jm = jp_moras(chars)
    jr = [mora_romaji(x["m"]) for x in jm]
    kt = []  # (token, syllable position in reading)
    for p, ch in enumerate(reading):
        for t in hangul_tokens(ch):
            kt.append((t, p))
    n, m, GAP = len(kt), len(jr), 0.7
    INF = 1e9
    D = [[INF] * (m + 1) for _ in range(n + 1)]
    B = [[None] * (m + 1) for _ in range(n + 1)]
    D[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            if i and j and D[i - 1][j - 1] + _sim(kt[i - 1][0], jr[j - 1]) < D[i][j]:
                D[i][j] = D[i - 1][j - 1] + _sim(kt[i - 1][0], jr[j - 1]); B[i][j] = "d"
            if i and D[i - 1][j] + GAP < D[i][j]:
                D[i][j] = D[i - 1][j] + GAP; B[i][j] = "k"
            if j and D[i][j - 1] + GAP < D[i][j]:
                D[i][j] = D[i][j - 1] + GAP; B[i][j] = "j"
    spans: dict[int, list[float]] = {}
    i, j = n, m
    while i or j:
        b = B[i][j]
        if b == "d":
            p = kt[i - 1][1]; s, e = jm[j - 1]["s"], jm[j - 1]["e"]
            cur = spans.setdefault(p, [s, e]); cur[0] = min(cur[0], s); cur[1] = max(cur[1], e)
            i -= 1; j -= 1
        elif b == "k":
            i -= 1
        else:
            if kt and i:  # an unmatched Japanese mora extends the Korean syllable that follows it
                p = kt[i - 1][1]
                cur = spans.setdefault(p, [jm[j - 1]["s"], jm[j - 1]["e"]])
                cur[0] = min(cur[0], jm[j - 1]["s"]); cur[1] = max(cur[1], jm[j - 1]["e"])
            j -= 1
    out = [{"c": ch, "s": spans[p][0] if p in spans else None, "e": spans[p][1] if p in spans else None}
           for p, ch in enumerate(reading)]
    return _fill_monotonic(out)


def _fill_monotonic(out: list[dict]) -> list[dict]:
    """Interpolate untimed syllables and keep starts non-decreasing."""
    idx = [k for k, c in enumerate(out) if c["s"] is not None]
    if not idx:
        return out
    for k, c in enumerate(out):
        if c["s"] is None:
            prev = max((q for q in idx if q < k), default=None)
            nxt = min((q for q in idx if q > k), default=None)
            if prev is None: c["s"] = c["e"] = out[nxt]["s"]
            elif nxt is None: c["s"] = c["e"] = out[prev]["e"]
            else:
                a, b = out[prev]["e"], out[nxt]["s"]
                frac = (k - prev) / (nxt - prev)
                c["s"] = c["e"] = a + (b - a) * frac
    for k in range(1, len(out)):
        if out[k]["s"] < out[k - 1]["s"]:
            out[k]["s"] = out[k - 1]["s"]
        if out[k]["e"] < out[k]["s"]:
            out[k]["e"] = out[k]["s"]
    return out


# ---------------------------------------------------------------- auto reading
KANA_KO = {
    "あ": "아", "い": "이", "う": "우", "え": "에", "お": "오", "か": "카", "き": "키", "く": "쿠", "け": "케", "こ": "코",
    "さ": "사", "し": "시", "す": "스", "せ": "세", "そ": "소", "た": "타", "ち": "치", "つ": "츠", "て": "테", "と": "토",
    "な": "나", "に": "니", "ぬ": "누", "ね": "네", "の": "노", "は": "하", "ひ": "히", "ふ": "후", "へ": "헤", "ほ": "호",
    "ま": "마", "み": "미", "む": "무", "め": "메", "も": "모", "や": "야", "ゆ": "유", "よ": "요",
    "ら": "라", "り": "리", "る": "루", "れ": "레", "ろ": "로", "わ": "와", "を": "오", "ゐ": "이", "ゑ": "에",
    "が": "가", "ぎ": "기", "ぐ": "구", "げ": "게", "ご": "고", "ざ": "자", "じ": "지", "ず": "즈", "ぜ": "제", "ぞ": "조",
    "だ": "다", "ぢ": "지", "づ": "즈", "で": "데", "ど": "도", "ば": "바", "び": "비", "ぶ": "부", "べ": "베", "ぼ": "보",
    "ぱ": "파", "ぴ": "피", "ぷ": "푸", "ぺ": "페", "ぽ": "포", "ゔ": "부",
    "きゃ": "캬", "きゅ": "큐", "きょ": "쿄", "しゃ": "샤", "しゅ": "슈", "しょ": "쇼", "ちゃ": "챠", "ちゅ": "츄", "ちょ": "쵸",
    "にゃ": "냐", "にゅ": "뉴", "にょ": "뇨", "ひゃ": "햐", "ひゅ": "휴", "ひょ": "효", "みゃ": "먀", "みゅ": "뮤", "みょ": "묘",
    "りゃ": "랴", "りゅ": "류", "りょ": "료", "ぎゃ": "갸", "ぎゅ": "규", "ぎょ": "교", "じゃ": "쟈", "じゅ": "쥬", "じょ": "죠",
    "びゃ": "뱌", "びゅ": "뷰", "びょ": "뵤", "ぴゃ": "퍄", "ぴゅ": "퓨", "ぴょ": "표", "ちぇ": "체", "しぇ": "셰", "じぇ": "제",
    "ふぁ": "파", "ふぃ": "피", "ふぇ": "페", "ふぉ": "포", "てぃ": "티", "でぃ": "디", "とぅ": "투", "うぃ": "위", "うぇ": "웨", "うぉ": "워",
}
PARTICLES = {"は", "を", "が", "の", "に", "へ", "と", "も", "で", "や", "か", "ね", "よ", "な", "さ", "から", "まで", "より",
             "だけ", "しか", "って", "けど", "のに", "ので", "たい", "ない", "た", "だ", "て", "です", "ます", "でしょう"}


def _add_final(syl: str, final: str) -> str:
    code = ord(syl) - 0xAC00
    if not 0 <= code < 11172 or code % 28:
        return syl + ("ㅅ" if final == "ㅅ" else "ㄴ")
    return chr(ord(syl) + JONG.index(final))


def auto_reading(chars: list[dict]) -> list[dict]:
    """Generate a Korean reading from the kana, timed mora-by-mora."""
    jm = jp_moras(chars)
    text = "".join(c["c"] for c in chars)
    toks = _kks.convert(text)
    # word boundaries (space before non-particle tokens) keyed by mora index
    starts, pos, particle_fix = set(), 0, {}
    for t in toks:
        h = kata_to_hira(t["hira"])
        n = len(split_moras(h))
        if n and pos and h not in PARTICLES:
            starts.add(pos)
        if h in ("は", "には", "では", "とは", "へ", "には", "ては", "のは"):  # particle は/へ read as わ/え
            particle_fix[pos + n - 1] = {"は": "わ", "へ": "え"}[h[-1]]
        pos += n
    out = []
    for k, m in enumerate(jm):
        if k in starts:
            out.append({"c": " ", "s": None, "e": None})
        mm = particle_fix.get(k, m["m"])
        if mm in ("っ", "ん") and out and out[-1]["c"] != " ":
            out[-1]["c"] = _add_final(out[-1]["c"], "ㅅ" if mm == "っ" else "ㄴ")
            out[-1]["e"] = m["e"]
            continue
        ko = KANA_KO.get(mm) or "".join(KANA_KO.get(ch, "") for ch in mm) or ("-" if mm == "ー" else mm)
        out.append({"c": ko, "s": m["s"], "e": m["e"]})
    # a multi-letter syllable string (rare fallback) is split into single display chars
    flat = []
    for c in out:
        if len(c["c"]) > 1 and c["c"] != " ":
            n = len(c["c"])
            for j, ch in enumerate(c["c"]):
                s, e = c["s"], c["e"]
                flat.append({"c": ch, "s": None if s is None else s + (e - s) * j / n,
                             "e": None if s is None else s + (e - s) * (j + 1) / n})
        else:
            flat.append(c)
    return _fill_monotonic(flat)
