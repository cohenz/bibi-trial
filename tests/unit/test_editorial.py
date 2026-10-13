"""House style on generated text (13.10.2026): the indictment's shorthand is spelled out for readers."""

from ntk_common import editorial


def test_full_term():
    p = editorial.polish_text
    assert p("נתניהו קיבל היענות חריגה באתר וואלה") == "נתניהו קיבל היענות חריגה לדרישות סיקור באתר וואלה"
    assert p("בהיענות חריגה מתוך ציפייה") == "בהיענות חריגה לדרישות סיקור מתוך ציפייה"
    assert p("היענות חריגה לדרישות סיקור באתר") == "היענות חריגה לדרישות סיקור באתר"  # already whole
    assert p("היענות חריגה של אתר וואלה לדרישות סיקור") == "היענות חריגה של אתר וואלה לדרישות סיקור"
    assert p("הדרישה נענתה וההיענות חריגה") == "הדרישה נענתה וההיענות חריגה"  # a predicate, not the term
    # quoted words stay as said or written (review 13.10.2026)
    assert p('בעדותו אמר: "לא הייתה שום היענות חריגה"') == 'בעדותו אמר: "לא הייתה שום היענות חריגה"'
    assert p('"היענות חריגה" של אתר וואלה לדרישות סיקור') == '"היענות חריגה" של אתר וואלה לדרישות סיקור'
    assert p("״היענות חריגה״ לדרישות") == "״היענות חריגה״ לדרישות"
    assert p("היענות חריגה לבקשות הסיקור") == "היענות חריגה לבקשות הסיקור"
    assert p("היענות חריגה, לטענת התביעה, לדרישות") == "היענות חריגה, לטענת התביעה, לדרישות"
    assert p("עו״ד חן שאל על היענות חריגה וב״כ המדינה התנגד") == "עו״ד חן שאל על היענות חריגה לדרישות סיקור וב״כ המדינה התנגד"
    assert p('אמר: "עו״ד חן, לא הייתה היענות חריגה"') == 'אמר: "עו״ד חן, לא הייתה היענות חריגה"'
    assert p("קיבל היענות חריגה; בתמורה קידם") == "קיבל היענות חריגה לדרישות סיקור; בתמורה קידם"


def test_only_prose_fields_change():
    doc = {"summary_sentences": [{"text": "היענות חריגה", "citation_ids": ["su_x"]}],
           "citations": [{"quote": "היענות חריגה", "source_unit_id": "su_x"}]}
    out = editorial.polish(doc)
    assert out["summary_sentences"][0]["text"] == editorial.FULL_TERM
    assert out["citations"][0]["quote"] == "היענות חריגה"  # a quote from the source stays exact
    assert doc["summary_sentences"][0]["text"] == "היענות חריגה"  # the stored payload is not touched
