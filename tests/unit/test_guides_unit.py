"""Reader guides (ADR-0015): indictment sections, allegation framing, witness names and dates."""

from ntk_common import guides
from ntk_common.layers import UnitView


def _u(i: int, text: str) -> UnitView:
    return UnitView(id=f"su_{i:026x}", source_version_id="sv_" + "0" * 26, page=1, line_start=i, line_end=i,
                    speaker_label=None, speaker_role=None, unit_type="other", text=text)


def test_split_indictment_sections_and_appendix_owner():
    texts = ["כתב אישום", "חלק כללי\nהנאשמים", "1. הנאשם א' כיהן כשר.", "תמצית האישום הראשון – פרשת \"4000\"", "תמצית.",
             "האישום הראשון – פרשת 4000 )הנאשמים(", "העובדות: מצ\"ב כנספח \"א\" לכתב האישום.", "הוראות החיקוק לפיהן מואשמים",
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
    assert guides.witness_name("השר זאב אלקין") == ("זאב אלקין", "השר")
    assert guides.witness_name('רס"מ טליה שור') == ("טליה שור", 'רס"מ')
    assert guides.witness_name("מר כהן") == ("מר כהן", None)  # a title with a single name stays as printed
    assert guides.witness_slug("אילן ישועה") == guides.witness_slug(" אילן  ישועה ")
    assert guides.witness_slug("אילן ישועה").startswith("w_") and len(guides.witness_slug("x")) == 12
    assert guides.name_matches("אילן ישועה", "לפי כתב האישום, ישועה היה מנכ\"ל")
    assert not guides.name_matches("ניר חפץ", "חפצים רבים")
    assert guides._norm_date("2015-03-12", "day") == ("2015-03-12", "day")
    assert guides._norm_date("2015-03", "day") == ("2015-03-01", "month")
    assert guides._norm_date("2015-03-12", "year") == ("2015-01-01", "year")
    assert guides._norm_date("1999", "year") is None and guides._norm_date("12.3.2015", "day") is None


def test_batch_request_uses_snake_case_fields():
    from ntk_common.llm.providers import GeminiProvider, batch_request

    body = GeminiProvider.request_body(system="S", user="U", temperature=0.1,
                                       response_schema={"type": "object", "additionalProperties": False,
                                                        "properties": {"a": {"type": "string"}}})
    b = batch_request(body)
    assert b["system_instruction"] == {"parts": [{"text": "S"}]} and "systemInstruction" not in b
    g = b["generation_config"]
    assert g["response_mime_type"] == "application/json" and g["temperature"] == 0.1
    assert g["response_json_schema"]["additionalProperties"] is False  # schema keywords untouched
    assert b["contents"] == body["contents"]


def test_batch_quota_split_sends_what_fits():
    """A group refused for quota (429) is halved until the provider accepts; what never fits is returned unsent."""
    from ntk_common.batches import _create_split
    from ntk_common.llm.providers import ProviderError

    class P:
        def __init__(self, cap):
            self.cap, self.waiting, self.calls = cap, 0, []

        def create_batch(self, *, model_id, items, display_name):
            self.calls.append(len(items))
            if self.waiting + len(items) > self.cap:
                raise ProviderError("gemini HTTP 429: quota", retryable=True, status=429)
            self.waiting += len(items)
            return f"batches/{display_name}"

    items = [{"key": f"k{i}", "request": {}} for i in range(10)]
    p = P(cap=6)
    sent, left, err = _create_split(p, "m", items, "g")
    assert sum(len(g) for _, g in sent) == 6 and len(left) == 4 and err  # fills up to the cap (5, then 1), keeps the rest
    assert sorted(x["key"] for _, g in sent for x in g) + sorted(x["key"] for x in left) == sorted(x["key"] for x in items)
    p = P(cap=100)
    sent, left, err = _create_split(p, "m", items, "g")
    assert len(sent) == 1 and not left and err is None and p.calls == [10]
    p = P(cap=0)
    sent, left, err = _create_split(p, "m", items, "g")
    assert not sent and len(left) == 10 and p.calls == [10, 5, 2, 1]  # stops after the first half fails at one
    try:
        _create_split(type("E", (), {"create_batch": lambda self, **k: (_ for _ in ()).throw(ProviderError("x", retryable=False, status=400))})(), "m", items, "g")
        raise AssertionError("non-quota errors must propagate")
    except ProviderError:
        pass
