"""House style on generated text (13.10.2026): the indictment's shorthand is spelled out for readers."""

from ntk_common import editorial


def test_full_term():
    p = editorial.polish_text
    assert p("נתניהו קיבל היענות חריגה באתר וואלה") == "נתניהו קיבל היענות חריגה לדרישות סיקור באתר וואלה"
    assert p("בהיענות חריגה מתוך ציפייה") == "בהיענות חריגה לדרישות סיקור מתוך ציפייה"
    assert p("היענות חריגה לדרישות סיקור באתר") == "היענות חריגה לדרישות סיקור באתר"  # already whole
    assert p("היענות חריגה של אתר וואלה לדרישות סיקור") == "היענות חריגה של אתר וואלה לדרישות סיקור"
    assert p("הדרישה נענתה וההיענות חריגה") == "הדרישה נענתה וההיענות חריגה"  # a predicate, not the term


def test_only_prose_fields_change():
    doc = {"summary_sentences": [{"text": "היענות חריגה", "citation_ids": ["su_x"]}],
           "citations": [{"quote": "היענות חריגה", "source_unit_id": "su_x"}]}
    out = editorial.polish(doc)
    assert out["summary_sentences"][0]["text"] == editorial.FULL_TERM
    assert out["citations"][0]["quote"] == "היענות חריגה"  # a quote from the source stays exact
    assert doc["summary_sentences"][0]["text"] == "היענות חריגה"  # the stored payload is not touched
