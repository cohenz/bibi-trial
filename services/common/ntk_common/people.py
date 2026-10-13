"""People's names as printed in court papers → one identity per person.

The same witness is printed in many ways: "מר אילן ישועה" / "אילן ישועה", "אלעד אבירם" / "אבירם אלעד",
"פולינה גובזמן-קריב" / "פולינה גובזמן קריב", "עדי קופלוביץ" / "עדי קופלוביץ'", "שלמה (מומי) משולם",
"אבי ברגר, בחקירה נגדית לעו"ד …", a misspelling in one protocol ("יינון מגל", "אלי ללוי"), or a line the
parser took for a name ("המשך חקירה נגדית לעו"ד …"). This module turns those into one entry per person:

1. ``clean_name``: strip titles (repeatedly), defendant labels, and trailing descriptions of the testimony.
2. ``strict_key``: order-, hyphen-, geresh- and parenthesis-insensitive key — merged automatically.
3. ``loose_key``: also ignores ו/י and doubled letters (Hebrew spelling variants and typos) — merged only
   when both spellings appear within ``LOOSE_WINDOW_DAYS`` of each other.
4. ``ALIASES``: hand-checked pairs no rule can see (a nickname, a wrong first name in one protocol).
5. Lines that are not names are attached to a known person whose name they contain, or dropped.

What stays doubtful is reported by ``suspects`` for a person to decide, never merged silently.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from . import hebrew

LOOSE_WINDOW_DAYS = 90

_Q = "[\"״'׳]"  # gershayim / geresh as typed
_DEFENDANT = re.compile(r"^\s*(נאש[םמ]ת?\s*\d+)\s*[—–-]?\s*")
# role or rank: kept as a label ("השר זאב אלקין" → label "השר")
_ROLE = re.compile(rf"^\s*(השר(?:ה)?|ח{_Q}כ|רס{_Q}[מבל]|רפ{_Q}ק|פקד|סנ{_Q}צ|תנ{_Q}צ|נצ{_Q}מ|ניצב|ד{_Q}ר|פרופ{_Q}?)\s+")
# honorifics and witness markers: dropped
_HONORIFIC = re.compile(rf"^\s*(מר|גב{_Q}|הגב{_Q}|הגברת|העד(?:ה)?|עד(?:ת)?\s+(?:ה)?(?:תביעה|הגנה)|עו{_Q}ד)\s+")
# a description of the testimony after the name
_TAIL = re.compile(r"\s*(?:,|;|\s[—–-]\s|\(?\s*(?:ב|ל)?(?:המשך|חקירה|חקירתו|חקירתה|נחקר|נחקרה|עדותו|עדותה)\b).*$")
_NOT_A_NAME = re.compile(r"חקיר|המשך|מספר זיהוי|\bצד\s+[אב]\b|\d")
_CODE_ONLY = re.compile(rf"^\s*ע{_Q}?[הת]\s*\d+\s*$")
_PARENS = re.compile(r"\([^)]*\)")

_ALIASES_FILE = Path(__file__).with_name("data") / "person_aliases.json"


def _load_aliases() -> dict[str, str]:
    try:
        raw = json.loads(_ALIASES_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    return {strict_key(k): v for k, v in raw.get("aliases", {}).items()}


def clean_name(raw: str) -> tuple[str | None, str | None]:
    """Printed witness string → (name, label). ``name`` is None when the string is not a person's name.

    'נאשם 1 — בנימין נתניהו' → ('בנימין נתניהו', 'נאשם 1'); 'העד מר אילן ישועה' → ('אילן ישועה', None);
    'השר זאב אלקין' → ('זאב אלקין', 'השר'); 'אבי ברגר, בחקירה נגדית …' → ('אבי ברגר', None)."""
    s = hebrew.normalize(raw or "").replace("\n", " ").strip()
    if not s or _CODE_ONLY.match(s):
        return None, None
    label = None
    m = _DEFENDANT.match(s)
    if m:
        label, s = re.sub(r"\s+", " ", m.group(1)).strip(), s[m.end():]
    for _ in range(4):  # "העד מר …", "נאשם 1 מר …"
        r = _ROLE.match(s)
        h = _HONORIFIC.match(s)
        if r and len(s[r.end():].split()) >= 2:
            label, s = label or r.group(1), s[r.end():]
        elif h and len(s[h.end():].split()) >= 2:
            s = s[h.end():]
        else:
            break
    s = _TAIL.sub("", s).strip()
    s = re.sub(r"\s*-\s*", "-", s)  # "ברנע -פרגו" → "ברנע-פרגו"
    s = re.sub(r"\s+", " ", s).strip(" .,:;-–—")
    if not s or _NOT_A_NAME.search(s) or len(s.split()) > 5:
        return None, label
    return s, label


def _tokens(name: str) -> list[str]:
    s = hebrew.normalize(name)
    s = _PARENS.sub(" ", s)
    s = re.sub(rf"{_Q}", "", s)
    s = re.sub(r"[-–—.,]", " ", s)
    return [t for t in s.split() if t]


def strict_key(name: str) -> str:
    """Same person when the same words appear, in any order and with any hyphen/geresh/nickname."""
    return " ".join(sorted(_tokens(name)))


def _loose_token(t: str) -> str:
    t = re.sub(r"(.)\1+", r"\1", t)  # doubled letters: "ללוי" → "לוי"
    return t[0] + re.sub("[וי]", "", t[1:]) if len(t) > 2 else t  # spelling with or without ו/י


def loose_key(name: str) -> str:
    return " ".join(sorted(_loose_token(t) for t in _tokens(name)))


ALIASES = _load_aliases()


def _days(a: str, b: str) -> int:
    return abs((dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days)


class Person:
    """One identity and every way its name was printed."""

    def __init__(self, name: str):
        self.forms: dict[str, int] = {name: 0}  # cleaned name → times seen (an alias target starts at 0)
        self.labels: dict[str, int] = {}
        self.dates: list[str] = []

    def add(self, name: str, label: str | None, date: str | None, n: int = 1) -> None:
        self.forms[name] = self.forms.get(name, 0) + n
        if label:
            self.labels[label] = self.labels.get(label, 0) + n
        if date:
            self.dates.append(date)

    @property
    def name(self) -> str:
        """The most printed form; on a tie one without a nickname in brackets, then the hyphenated / geresh form."""
        return max(self.forms, key=lambda f: (self.forms[f], "(" not in f, "-" in f or "'" in f or "׳" in f, len(f)))

    @property
    def label(self) -> str | None:
        return max(self.labels, key=self.labels.get) if self.labels else None


class Resolver:
    """Collect (raw, date) mentions, then ``resolve()`` → raw string → Person."""

    def __init__(self) -> None:
        self.mentions: list[tuple[str, str | None]] = []

    def add(self, raw: str, date: str | None = None) -> None:
        self.mentions.append((raw, date))

    def resolve(self) -> dict[str, Person]:
        people: dict[str, Person] = {}  # strict key → person
        cleaned: dict[str, tuple[str | None, str | None]] = {}
        for raw, date in self.mentions:
            name, label = cleaned.setdefault(raw, clean_name(raw))
            if not name:
                continue
            target = ALIASES.get(strict_key(name))
            key = strict_key(target) if target else strict_key(name)
            p = people.get(key)
            if p is None:
                p = people[key] = Person(target or name)
            p.add(target or name, label, date)  # an alias counts for the checked spelling
        self._merge_loose(people)
        out: dict[str, Person] = {}
        by_key = {k: p for k, p in people.items()}
        for raw, _date in self.mentions:
            name, label = cleaned[raw]
            if name:
                target = ALIASES.get(strict_key(name))
                out[raw] = by_key[strict_key(target) if target else strict_key(name)]
                continue
            p = self._rescue(raw, label, people)
            if p is not None:
                out[raw] = p
        return out

    @staticmethod
    def _merge_loose(people: dict[str, Person]) -> None:
        """Spelling variants within LOOSE_WINDOW_DAYS: fold the less printed form into the more printed one."""
        groups: dict[str, list[str]] = {}
        for k, p in people.items():
            if len(k.split()) >= 2:
                groups.setdefault(loose_key(p.name), []).append(k)
        for keys in groups.values():
            if len(keys) < 2:
                continue
            keys.sort(key=lambda k: -sum(people[k].forms.values()))
            main = people[keys[0]]
            for k in keys[1:]:
                other = people[k]
                if main.dates and other.dates and min(_days(a, b) for a in main.dates for b in other.dates) > LOOSE_WINDOW_DAYS:
                    continue
                for f, n in other.forms.items():
                    main.forms[f] = main.forms.get(f, 0) + n
                for lb, n in other.labels.items():
                    main.labels[lb] = main.labels.get(lb, 0) + n
                main.dates += other.dates
                people[k] = main

    @staticmethod
    def _rescue(raw: str, label: str | None, people: dict[str, Person]) -> Person | None:
        """A line that is not a name: the known person whose every word it contains, else the person with the same
        defendant label ("המשך חקירה נגדית …" printed under "נאשם 1")."""
        words = set(_tokens(raw))
        hits = {id(p): p for p in people.values() if len(p.name.split()) >= 2 and set(_tokens(p.name)) <= words}
        if len(hits) == 1:
            return next(iter(hits.values()))
        if label and label.startswith("נאש"):
            same = {id(p): p for p in people.values() if p.label == label}
            if len(same) == 1:
                return next(iter(same.values()))
        return None


def suspects(people: list[Person]) -> list[tuple[str, str, str]]:
    """Pairs that may be one person but are not merged: the same family name with first names one letter apart,
    or the same first name and family names one letter apart, within LOOSE_WINDOW_DAYS. For a person to decide."""

    def one_apart(a: str, b: str) -> bool:
        if a == b or abs(len(a) - len(b)) > 1:
            return False
        if len(a) == len(b):
            return sum(x != y for x, y in zip(a, b, strict=True)) == 1
        s, t = sorted((a, b), key=len)
        return any(t[:i] + t[i + 1:] == s for i in range(len(t)))

    out = []
    uniq = list({id(p): p for p in people}.values())
    for i, p in enumerate(uniq):
        for q in uniq[i + 1:]:
            a, b = _tokens(p.name), _tokens(q.name)
            if len(a) != len(b) or len(a) < 2:
                continue
            diff = [(x, y) for x, y in zip(a, b, strict=True) if x != y]
            close = p.dates and q.dates and min(_days(x, y) for x in p.dates for y in q.dates) <= LOOSE_WINDOW_DAYS
            if len(diff) == 1 and close and (one_apart(*diff[0]) or a[-1] == b[-1]):
                out.append((p.name, q.name, "same family name" if a[-1] == b[-1] else "one letter apart"))
    return out


# --- judges -----------------------------------------------------------------------------------------------------
PANEL = ("רבקה פרידמן-פלדמן", "משה בר-עם", "עודד שחם")  # the trial bench (ת"פ 67104-01-20)


def clean_judges(names: list[str] | None) -> list[str]:
    """Judges as printed in a protocol → clean, unique names. An entry naming a member of the trial bench (by family
    name, whatever the spacing, initials or OCR noise around it) becomes that judge; any other entry is kept only when
    it reads as a name (2–4 Hebrew words, no digits or Latin letters, no one-letter words)."""
    out: list[str] = []
    for raw in names or []:
        s = hebrew.normalize(raw or "")
        s = re.sub(r"\s*[-–—]\s*", "-", s).strip(" .,:;()")
        s = re.sub(r"\s+", " ", s)
        flat = s.replace("-", "")
        bench = next((j for j in PANEL if j.split()[-1].replace("-", "") in flat), None)
        if bench:
            name = bench
        elif (not s or re.search(r"\d|[A-Za-z]", s) or not 2 <= len(s.split()) <= 4
              or any(len(set(w.strip("׳'\""))) < 2 for w in s.split())):  # an initial ("ע׳", OCR "יי")
            continue
        else:
            name = s
        if name not in out:
            out.append(name)
    return out
