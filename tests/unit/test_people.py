"""One identity per person, whatever the protocol printed (12.10.2026: the witness list showed "מר אילן ישועה"
next to "אילן ישועה", three spellings of אבירם אלעד, and "אבי ברגר, בחקירה נגדית …" as its own witness)."""

from __future__ import annotations

from ntk_common import people


def _resolve(mentions):
    r = people.Resolver()
    for raw, date in mentions:
        r.add(raw, date)
    m = r.resolve()
    return m, {id(p): p for p in m.values()}


def test_clean_name_strips_titles_labels_and_descriptions():
    assert people.clean_name("העד מר אילן ישועה") == ("אילן ישועה", None)
    assert people.clean_name("נאשם 1 מר בנימין נתניהו") == ("בנימין נתניהו", "נאשם 1")
    assert people.clean_name("נאשם 1 — בנימין נתניהו") == ("בנימין נתניהו", "נאשם 1")
    assert people.clean_name("השר זאב אלקין") == ("זאב אלקין", "השר")
    assert people.clean_name('אבי ברגר, בחקירה נגדית לעו"ד בעז בן-צור') == ("אבי ברגר", None)
    assert people.clean_name("דב פיינטוך בהמשך חקירה נגדית") == ("דב פיינטוך", None)
    assert people.clean_name("שלומית ברנע -פרגו") == ("שלומית ברנע-פרגו", None)
    assert people.clean_name("מר כהן") == ("מר כהן", None)  # a title with a single name stays as printed


def test_lines_that_are_not_names():
    assert people.clean_name('ע"ה 23')[0] is None
    assert people.clean_name('המשך חקירה נגדית לעו"ד יהודית תירוש')[0] is None
    assert people.clean_name("מספר זיהוי צד ב בנימין נתניהו")[0] is None


def test_word_order_hyphens_geresh_and_nicknames_merge():
    m, ps = _resolve([
        ("מר אבירם אלעד", "2021-10-11"), ("מר אלעד אבירם", "2021-10-12"), ("אבירם אלעד", "2021-10-13"),
        ("פולינה גובזמן-קריב", "2022-12-26"), ("פולינה גובזמן קריב", "2022-12-27"),
        ("עדי קופלוביץ", "2022-11-21"), ("עדי קופלוביץ'", "2022-11-22"), ("עדי קופלוביץ'", "2022-11-23"),
        ("שלמה (מומי) משולם", "2023-04-17"), ("שלמה משולם", "2023-04-18"),
    ])
    assert len(ps) == 4
    assert m["מר אלעד אבירם"] is m["אבירם אלעד"]
    assert m["פולינה גובזמן קריב"].name == "פולינה גובזמן-קריב"  # on a tie, the hyphenated spelling
    assert m["עדי קופלוביץ"].name.endswith("ץ׳")  # the more printed form wins
    assert m["שלמה (מומי) משולם"].name == "שלמה משולם"


def test_spelling_variants_merge_only_when_close_in_time():
    m, _ = _resolve([("ינון מגל", "2023-07-18"), ("ינון מגל", "2023-09-11"), ("יינון מגל", "2023-07-19"),
                     ("אלי לוי", "2026-05-31"), ("אלי ללוי", "2026-06-21")])
    assert m["יינון מגל"] is m["ינון מגל"] and m["ינון מגל"].name == "ינון מגל"
    assert m["אלי ללוי"] is m["אלי לוי"]
    m, _ = _resolve([("דוד שמרון", "2019-01-01"), ("דוד שימרון", "2024-07-10")])
    assert m["דוד שמרון"] is not m["דוד שימרון"]  # years apart: not merged on spelling alone


def test_non_names_attach_to_the_person_they_name_or_share_a_defendant_label():
    m, ps = _resolve([("נאשם 1 — בנימין נתניהו", "2025-02-10"), ("נאשם 1 — מספר זיהוי צד ב בנימין נתניהו", "2025-03-24"),
                      ('נאשם 1 — המשך חקירה נגדית לעו"ד יהודית תירוש', "2026-01-19"), ('ע"ה 23', "2026-07-12")])
    assert len(ps) == 1
    p = m["נאשם 1 — בנימין נתניהו"]
    assert m["נאשם 1 — מספר זיהוי צד ב בנימין נתניהו"] is p
    assert m['נאשם 1 — המשך חקירה נגדית לעו"ד יהודית תירוש'] is p
    assert 'ע"ה 23' not in m and p.label == "נאשם 1"


def test_checked_aliases_and_suspects():
    m, ps = _resolve([("אהוד הירש", "2023-07-11"), ("אודי הירש", "2023-07-12"), ("אהוד הירש", "2023-07-18")])
    assert len(ps) == 1 and m["אודי הירש"].name == "אהוד הירש"
    _, ps = _resolve([("בועז סטמבלר", "2022-01-31"), ("ארז סטמבלר", "2022-01-31")])
    sus = people.suspects(list(ps.values()))
    assert len(ps) == 2 and len(sus) == 1  # reported for a person to decide, never merged silently


def test_clean_judges():
    assert people.clean_judges(["משה בר – עם", "משה בר-עם", "רבקה פרידמן – פלדמן", "עודד שחם 5",
                                "פעלה והשקיעה מאמצ וממון ניכר בשיפוץ", "עודד שחם"]) == \
        ["משה בר-עם", "רבקה פרידמן-פלדמן", "עודד שחם"]
