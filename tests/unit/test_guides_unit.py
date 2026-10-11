"""Reader guides (ADR-0015): indictment sections, allegation framing, witness names and dates."""

from ntk_common import guides
from ntk_common.layers import UnitView


def _u(i: int, text: str) -> UnitView:
    return UnitView(id=f"su_{i:026x}", source_version_id="sv_" + "0" * 26, page=1, line_start=i, line_end=i,
                    speaker_label=None, speaker_role=None, unit_type="other", text=text)


def test_split_indictment_sections_and_appendix_owner():
    texts = ["כתב אישום", "חלק כללי\nהנאשמים", "1. הנאשם א' כיהן כשר.", "תמצית האישום הראשון – פרשת \"4000\"", "תמצית.",
             "האישום הראשון – פרשת 4000 )הנאשמים(", "העובדות: ראו נספח א'.", "הוראות החיקוק לפיהן מואשמים",
             "האישום השני – פרשת 2000 )הנאשם(", "עובדות 2000.", "האישום השלישי – הפרת אמונים בפרשת 1000 )הנאשם(",
             "עובדות 1000.", "עדי התביעה:", "1. עד", "נספח א' – דוגמאות", "דוגמה 1", "נספח ב' – טבלת 1000", "שורה"]
    p = guides.split_indictment([_u(i, t) for i, t in enumerate(texts)])
    assert p.count_order == ["4000", "2000", "1000"]
    assert [u.text for u in p.general] == ["חלק כללי\nהנאשמים", "1. הנאשם א' כיהן כשר."]
    assert len(p.summary) == 2 and len(p.counts["4000"]) == 3 and len(p.counts["1000"]) == 2
    assert [u.text for u in p.appendices["4000"]] == ["נספח א' – דוגמאות", "דוגמה 1"]
    assert [u.text for u in p.appendices["1000"]] == ["נספח ב' – טבלת 1000", "שורה"]  # owner from its own heading


def test_allegation_framing():
    assert guides.find_unframed_guilt("הנאשם קיבל שוחד מהמו\"ל") == ["קיבל שוחד"]
    assert guides.find_unframed_guilt("לפי כתב האישום, הנאשם קיבל שוחד") == []
    assert guides.find_unframed_guilt("כתב האישום מייחס לו לקיחת שוחד") == []
    assert guides.find_unframed_guilt("הוכח שהנאשם נפגש עמו") == ["הוכח"]


def test_witness_names_slugs_and_dates():
    assert guides.witness_name("נאשם 1 — בנימין נתניהו") == ("בנימין נתניהו", "נאשם 1")
    assert guides.witness_name("אילן ישועה") == ("אילן ישועה", None)
    assert guides.witness_slug("אילן ישועה") == guides.witness_slug(" אילן  ישועה ")
    assert guides.witness_slug("אילן ישועה").startswith("w_") and len(guides.witness_slug("x")) == 12
    assert guides.name_matches("אילן ישועה", "לפי כתב האישום, ישועה היה מנכ\"ל")
    assert not guides.name_matches("ניר חפץ", "חפצים רבים")
    assert guides._norm_date("2015-03-12", "day") == ("2015-03-12", "day")
    assert guides._norm_date("2015-03", "day") == ("2015-03-01", "month")
    assert guides._norm_date("2015-03-12", "year") == ("2015-01-01", "year")
    assert guides._norm_date("1999", "year") is None and guides._norm_date("12.3.2015", "day") is None
