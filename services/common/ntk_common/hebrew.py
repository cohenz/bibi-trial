"""Hebrew text normalisation and search-form generation (spec §11.2, §29.1).

Rules:
* raw text is never modified; normalised text is a separate field;
* case numbers, dates and exhibit marks are preserved verbatim;
* the derived search forms (prefix-stripped forms, character n-grams,
  abbreviation/alias expansions) are computed at ingestion time.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

NORMALIZER_VERSION = "he-norm-1.1"

HEBREW_LETTERS = "אבגדהוזחטיכלמנסעפצקרשתךםןףץ"
FINAL_LETTERS = "ךםןףץ"
FINAL_TO_REGULAR = str.maketrans({"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"})

_BIDI_CONTROLS = dict.fromkeys(
    map(ord, "‎‏‪‫‬‭‮⁦⁧⁨⁩﻿­​‌‍"), None
)
# Niqqud and cantillation marks; maqaf (U+05BE) handled separately.
_NIQQUD_RE = re.compile("[֑-ׇֽֿׁׂׅׄ]")
_PRESENTATION_RE = re.compile("[יִ-ﭏ]")
_HEB = f"[{HEBREW_LETTERS}]"
_GERESH_RE = re.compile(rf"(?<={_HEB})['’`´׳](?!{_HEB})|(?<={_HEB})['’`´](?={_HEB})")
_GERSHAYIM_RE = re.compile(rf"(?<={_HEB})[\"”“״](?={_HEB})")
_WS_RE = re.compile(r"[ \t  -   　]+")
_OCR_FIXES = [
    (re.compile(r"װ"), "וו"),
    (re.compile(r"ױ"), "וי"),
    (re.compile(r"ײ"), "יי"),
    (re.compile(r"[|¦](?=\s|$)"), ""),
    (re.compile(r"[‐‑‒–—−]"), "-"),
    (re.compile(r"…"), "..."),
]

TOKEN_RE = re.compile(
    r"\d{1,6}-\d{2}-\d{2}"  # case numbers 67104-01-20
    r"|\d{1,2}[./]\d{1,2}[./]\d{2,4}"  # dates
    r"|[נת]/\d+[א-ת]?"  # exhibits ת/123, נ/45
    r"|[A-Za-z][A-Za-z0-9_.-]*"
    r"|\d+(?:[.,]\d+)*"
    rf"|{_HEB}+(?:[״׳\"']{_HEB}*)*"
)

# Abbreviations and aliases used in court protocols. Values are expansions
# that are *added* as search terms; the original token is always kept.
ABBREVIATIONS: dict[str, list[str]] = {
    "עו״ד": ["עורך דין", "עורכת דין"],
    "ב״כ": ["בא כוח", "באי כוח"],
    "כב׳": ["כבוד"],
    "רה״מ": ["ראש הממשלה"],
    "יועמ״ש": ["היועץ המשפטי לממשלה"],
    "היועמ״ש": ["היועץ המשפטי לממשלה"],
    "ת״פ": ["תיק פלילי"],
    "אב״ד": ["אב בית הדין"],
    "מנכ״ל": ["מנהל כללי"],
    "בזק": ["בזק"],
    "ש.": ["שאלה"],
    "ת.": ["תשובה"],
    "ע״י": ["על ידי"],
    "וכו׳": ["וכולי"],
    "הנ״ל": ["הנזכר לעיל"],
}

# Two-letter-or-longer prefix sequences that can precede a Hebrew stem.
PREFIX_SEQUENCES = sorted(
    {
        "ו", "ה", "ב", "כ", "ל", "מ", "ש",
        "וה", "וב", "וכ", "ול", "ומ", "וש",
        "שה", "שב", "שכ", "של", "שמ", "כש", "מה", "לכש", "וכש",
        "ושה", "ושב", "ושל", "ושמ", "ומה", "ולכש", "שלכ",
    },
    key=len,
    reverse=True,
)

# Small high-frequency lexicon used to detect visual (reversed) Hebrew order.
_COMMON_WORDS = {
    "של", "את", "על", "לא", "זה", "הוא", "היא", "אני", "כן", "עם", "גם", "אבל", "מה", "אם", "כי",
    "יש", "אין", "היה", "בית", "המשפט", "אתה", "לי", "לו", "כל", "אז", "רק", "עד", "אחרי", "לפני",
    "נכון", "שאלה", "תשובה", "השופטת", "השופט", "העד", "אנחנו", "הם", "זאת", "שלא", "אותו", "שלי",
    "פרוטוקול", "המאשימה", "הנאשמים", "נגד", "כבוד", "תודה", "בסדר", "אולי", "היום", "אחד", "שני",
}


def strip_bidi(text: str) -> str:
    return text.translate(_BIDI_CONTROLS)


def normalize(text: str) -> str:
    """Return search/display-normalised text. Never used as a citation key."""
    if not text:
        return ""
    s = unicodedata.normalize("NFC", text)
    s = strip_bidi(s)
    s = _PRESENTATION_RE.sub(lambda m: unicodedata.normalize("NFKC", m.group(0)), s)
    s = _NIQQUD_RE.sub("", s)
    s = s.replace("־", "-")  # maqaf
    for rx, repl in _OCR_FIXES:
        s = rx.sub(repl, s)
    s = _GERSHAYIM_RE.sub("״", s)
    s = _GERESH_RE.sub("׳", s)
    s = _WS_RE.sub(" ", s)
    s = "\n".join(line.strip() for line in s.split("\n"))
    return s.strip()


def fold(text: str) -> str:
    """Aggressive fold used only for matching: final letters → regular,
    geresh/gershayim removed, lowercase latin."""
    s = normalize(text).translate(FINAL_TO_REGULAR)
    s = s.replace("״", "").replace("׳", "").replace('"', "").replace("'", "")
    return s.lower()


def tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(normalize(text))


def is_hebrew_word(tok: str) -> bool:
    return bool(tok) and tok[0] in HEBREW_LETTERS


def prefix_forms(token: str) -> list[str]:
    """All plausible stems after removing a grammatical prefix sequence.

    Over-generation is intended (recall); ranking happens later."""
    tok = token.replace("״", "").replace("׳", "")
    if not is_hebrew_word(tok) or len(tok) < 3:
        return []
    out: list[str] = []
    for pre in PREFIX_SEQUENCES:
        if tok.startswith(pre):
            stem = tok[len(pre) :]
            min_len = 3  # 2-letter stems add more noise than recall; pg_trgm covers them
            if len(stem) >= min_len and stem not in out:
                out.append(stem)
    return out


def char_ngrams(text: str, n: int = 3) -> list[str]:
    """Distinct character n-grams over folded words (padded with spaces)."""
    grams: list[str] = []
    seen: set[str] = set()
    for tok in tokens(text):
        f = fold(tok)
        if len(f) < 2:
            continue
        padded = f" {f} "
        for i in range(len(padded) - n + 1):
            g = padded[i : i + n]
            if g not in seen:
                seen.add(g)
                grams.append(g)
    return grams


def search_terms(text: str, aliases: dict[str, list[str]] | None = None) -> list[str]:
    """Folded tokens + prefix-stripped forms + abbreviation/alias expansions."""
    out: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        t = fold(term)
        if t and t not in seen:
            seen.add(t)
            out.append(t)

    norm = normalize(text)
    for tok in tokens(norm):
        add(tok)
        for stem in prefix_forms(tok):
            add(stem)
        for exp in ABBREVIATIONS.get(tok, []):
            for w in exp.split():
                add(w)
    if aliases:
        folded_text = fold(norm)
        for canonical, alts in aliases.items():
            names = [canonical, *alts]
            if any(fold(n) and fold(n) in folded_text for n in names):
                for n in names:
                    for w in n.split():
                        add(w)
    return out


def expand_query(query: str, aliases: dict[str, list[str]] | None = None) -> list[str]:
    return search_terms(query, aliases)


# ---------------------------------------------------------------------------
# Visual-order (reversed) Hebrew repair
# ---------------------------------------------------------------------------

_LTR_RUN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.,:/\-]*[A-Za-z0-9]|[A-Za-z0-9]")
_MIRROR = str.maketrans({"(": ")", ")": "(", "[": "]", "]": "[", "{": "}", "}": "{", "<": ">", ">": "<"})


def order_score(line: str) -> int:
    """Positive → looks logical (correct); negative → looks visual (reversed)."""
    score = 0
    for w in re.findall(rf"{_HEB}+", line):
        if len(w) >= 2:
            if w[-1] in FINAL_LETTERS:
                score += 1
            if w[0] in FINAL_LETTERS:
                score -= 1
        if w in _COMMON_WORDS:
            score += 2
        elif w[::-1] in _COMMON_WORDS:
            score -= 2
    return score


_OPEN, _CLOSE = "([{", ")]}"
_LATIN_RUN_RE = re.compile(r"[A-Za-z][A-Za-z0-9.,'’\-]*(?:[ ]+[A-Za-z][A-Za-z0-9.,'’\-]*)+")


def fix_bracket_direction(line: str) -> str:
    """'(הנאשם נתניהו)' printed in RTL may come out of a PDF as ')הנאשם נתניהו(' (or mirrored twice). A line whose
    first bracket closes and whose last bracket opens is reversed: swap every bracket on it. Lines like '1) …' or
    'א) … (ב)' are left alone."""
    brackets = [c for c in line if c in _OPEN or c in _CLOSE]
    if len(brackets) < 2 or brackets[0] not in _CLOSE or brackets[-1] not in _OPEN:
        return line
    return line.translate(_MIRROR)


def fix_latin_runs(line: str) -> str:
    """Reversing a visual RTL line puts a run of Latin words in reverse word order ('utmost my do will I'); restore
    it. Only applies to lines that are mostly Hebrew."""
    if hebrew_ratio(line) < 0.3:
        return line
    return _LATIN_RUN_RE.sub(lambda m: " ".join(reversed(m.group(0).split())), line)


def display_fix(text: str) -> str:
    """Repair direction artefacts of extractor versions before pdf-extract-1.1, line by line (display only: stored
    citation text never changes)."""
    if not text:
        return text
    return "\n".join(fix_latin_runs(fix_bracket_direction(ln)) for ln in text.split("\n"))


FIXED_EXTRACTOR = "pdf-extract-1.1"


def display_text(text: str, extractor_version: str | None) -> str:
    """Text as shown to readers: units extracted before ``FIXED_EXTRACTOR`` get ``display_fix``."""
    if extractor_version and extractor_version >= FIXED_EXTRACTOR:
        return text
    return display_fix(text)


def reverse_visual_line(line: str) -> str:
    """Convert a visually ordered RTL line to logical order."""
    rev = line[::-1].translate(_MIRROR)
    rev = _LTR_RUN_RE.sub(lambda m: m.group(0)[::-1], rev)
    return fix_latin_runs(fix_bracket_direction(rev))


def fix_visual_order(lines: Iterable[str]) -> tuple[list[str], bool]:
    """Detect page-level visual ordering and repair it.

    Decision is made on the whole page (sum of scores) so that a few
    ambiguous lines do not flip independently."""
    lines = list(lines)
    total = sum(order_score(ln) for ln in lines)
    if total < 0:
        return [reverse_visual_line(ln) for ln in lines], True
    return lines, False


def hebrew_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c in HEBREW_LETTERS) / len(letters)


def estimate_tokens(text: str) -> int:
    """Rough LLM-token estimate for Hebrew/mixed text (≈1.6 tokens/word).

    Used only for chunk sizing; exact counts come from the provider."""
    words = len(text.split())
    return max(1, int(round(words * 1.6)))
