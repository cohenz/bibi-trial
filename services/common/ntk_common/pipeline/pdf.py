"""PDF validation, text extraction and line reconstruction.

Stages covered: validate, extract_text, ocr_fallback, lineize (spec §27.2).

Extraction uses glyph positions (pdfplumber) so that

* lines are rebuilt from the page geometry rather than the content stream;
* right-to-left lines are converted from visual to logical order;
* printed line numbers in the page margin (standard in Israeli court
  protocols) are detected and kept as the *original* line numbers;
* repeated page headers/footers are tagged and kept out of speech turns.

If a page has no usable text layer the page is rasterised and OCR'd with
Tesseract (``heb`` + ``eng``). OCR'd pages and pages without printed line
numbers get synthetic line numbers and ``synthetic_lines=True``.
"""

from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass, field

from .. import hebrew

EXTRACTOR_VERSION = "pdf-extract-1.0"

PDF_MAGIC = b"%PDF-"
MIN_TEXT_CHARS_PER_PAGE = 40  # below this the text layer is considered unusable
MAX_PDF_BYTES = 200 * 1024 * 1024


class PdfValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Line:
    page: int
    line_no: int
    text: str
    kind: str = "body"  # body | header | footer | margin
    synthetic: bool = False
    top: float = 0.0


@dataclass
class PageText:
    page: int
    lines: list[Line] = field(default_factory=list)
    method: str = "text"  # text | ocr | empty
    visual_order_fixed: bool = False
    printed_line_numbers: bool = False
    char_count: int = 0


@dataclass
class ExtractedDocument:
    pages: list[PageText]
    page_count: int
    extractor_version: str = EXTRACTOR_VERSION
    warnings: list[str] = field(default_factory=list)

    @property
    def synthetic_lines(self) -> bool:
        return any(not p.printed_line_numbers for p in self.pages if p.lines)

    def body_lines(self) -> list[Line]:
        return [ln for p in self.pages for ln in p.lines if ln.kind == "body"]


def validate_pdf(data: bytes, *, declared_mime: str | None = None, expected_sha256: str | None = None,
                 max_bytes: int = MAX_PDF_BYTES) -> dict:
    """Check size, MIME, checksum and structural validity. Returns facts."""
    from ..ids import sha256_bytes

    if not data:
        raise PdfValidationError("empty_file", "file is empty")
    if len(data) > max_bytes:
        raise PdfValidationError("file_too_large", f"file is {len(data)} bytes; limit {max_bytes}")
    if declared_mime and declared_mime not in {"application/pdf", "application/x-pdf"}:
        raise PdfValidationError("unsupported_mime", f"declared MIME {declared_mime!r} is not a PDF")
    if not data[:1024].lstrip().startswith(PDF_MAGIC):
        raise PdfValidationError("not_a_pdf", "missing %PDF- header")
    digest = sha256_bytes(data)
    if expected_sha256 and expected_sha256.lower() != digest:
        raise PdfValidationError("checksum_mismatch", f"sha256 {digest} != expected {expected_sha256}")
    try:
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            try:
                if not reader.decrypt(""):
                    raise PdfValidationError("encrypted", "PDF is encrypted")
            except Exception as exc:  # noqa: BLE001
                raise PdfValidationError("encrypted", f"PDF is encrypted: {exc}") from exc
        page_count = len(reader.pages)
    except PdfValidationError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise PdfValidationError("corrupt_pdf", f"cannot parse PDF: {exc}") from exc
    if page_count < 1:
        raise PdfValidationError("no_pages", "PDF has no pages")
    return {"content_sha256": digest, "size_bytes": len(data), "page_count": page_count, "mime_type": "application/pdf"}


# ---------------------------------------------------------------------------
# geometry → lines
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(r"^\d{1,3}$")


def _group_lines(chars: list[dict], y_tol: float = 2.5) -> list[list[dict]]:
    rows: list[list[dict]] = []
    for ch in sorted(chars, key=lambda c: (round(c["top"], 1), c["x0"])):
        if rows and abs(rows[-1][0]["top"] - ch["top"]) <= y_tol:
            rows[-1].append(ch)
        else:
            rows.append([ch])
    return rows


def _split_margin_number(row: list[dict], width: float) -> tuple[int | None, list[dict]]:
    """Peel a printed line number off the outer edge of a row.

    Court protocols print line numbers in a narrow margin column that can sit
    closer to the text than a column gap (real files: number ends at 11% of
    the width, text starts at 14%). A run of digits at the very edge, separated
    from the text by at least one character width, is the margin number."""
    row = sorted(row, key=lambda c: c["x0"])
    solid = [c for c in row if c["text"].strip()]
    if not solid:
        return None, row
    for side in ("left", "right"):
        seq = solid if side == "left" else solid[::-1]
        run = []
        for c in seq:
            if not c["text"].isdigit():
                break
            if run:  # digits of one number touch; a gap means a new token
                gap = (c["x0"] - run[-1]["x1"]) if side == "left" else (run[-1]["x0"] - c["x1"])
                if gap > max(c.get("size", 10.0), 1.0) * 0.5:
                    break
            run.append(c)
        if not run or len(run) > 3:
            continue
        run_sorted = sorted(run, key=lambda c: c["x0"])
        x0, x1 = run_sorted[0]["x0"], run_sorted[-1]["x1"]
        size = max(run_sorted[0].get("size", 10.0), 1.0)
        rest = [c for c in solid if c not in run]
        if side == "left":
            if x1 > width * 0.15:
                continue
            if rest and min(c["x0"] for c in rest) - x1 < size * 0.9:
                continue
        else:
            if x0 < width * 0.85:
                continue
            if rest and x0 - max(c["x1"] for c in rest) < size * 0.9:
                continue
        number = int("".join(c["text"] for c in run_sorted))
        keep = [c for c in row if c not in run]
        return number, keep
    return None, row


def _row_segments(row: list[dict], gap_factor: float = 0.25) -> list[tuple[float, float, str]]:
    """Split a row into horizontally separated segments (x0, x1, visual text)."""
    row = sorted(row, key=lambda c: c["x0"])
    segments: list[tuple[float, float, str]] = []
    cur: list[dict] = []
    for ch in row:
        if cur:
            prev = cur[-1]
            size = max(prev.get("size", 10.0), 1.0)
            gap = ch["x0"] - prev["x1"]
            if gap > size * 2.5:  # column/margin gap
                segments.append(_seg(cur, gap_factor))
                cur = []
        cur.append(ch)
    if cur:
        segments.append(_seg(cur, gap_factor))
    return segments


def _seg(chars: list[dict], gap_factor: float) -> tuple[float, float, str]:
    out = []
    prev = None
    for ch in chars:
        if prev is not None:
            size = max(prev.get("size", 10.0), 1.0)
            if ch["x0"] - prev["x1"] > size * gap_factor and ch["text"] != " " and prev["text"] != " ":
                out.append(" ")
        out.append(ch["text"])
        prev = ch
    text = re.sub(r" {2,}", " ", "".join(out)).strip()
    return chars[0]["x0"], chars[-1]["x1"], text


def _to_logical(visual: str) -> str:
    if hebrew.hebrew_ratio(visual) >= 0.3:
        return hebrew.reverse_visual_line(visual)
    return visual


def extract_text_layer(data: bytes, only_pages: set[int] | None = None) -> list[PageText]:
    """Text layer per page. ``only_pages`` (1-based; negative counts from the end) limits extraction, e.g. {1, 2, -1}
    for classifying a document without reading all of it."""
    import pdfplumber

    pages: list[PageText] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        total = len(pdf.pages)
        wanted = None if only_pages is None else {p if p > 0 else total + 1 + p for p in only_pages}
        for idx, page in enumerate(pdf.pages, start=1):
            if wanted is not None and idx not in wanted:
                continue
            chars = [c for c in page.chars if c.get("text", "").strip() or c.get("text") == " "]
            width = float(page.width or 600)
            pt = PageText(page=idx)
            pt.char_count = sum(1 for c in chars if c["text"].strip())
            if pt.char_count < MIN_TEXT_CHARS_PER_PAGE:
                pt.method = "empty"
                pages.append(pt)
                continue
            raw_rows = []
            for full_row in _group_lines(chars):
                margin_no, row = _split_margin_number(full_row, width)
                if not row:  # the line held only its margin number
                    raw_rows.append((full_row[0]["top"], margin_no, ""))
                    continue
                segs = _row_segments(row) if any(c["text"].strip() for c in row) else []
                body_parts = []
                for x0, x1, txt in segs:
                    in_margin = x1 < width * 0.12 or x0 > width * 0.88
                    if in_margin and _NUM_RE.match(txt) and margin_no is None:
                        margin_no = int(txt)
                    elif txt:
                        body_parts.append((x0, txt))
                # RTL: rightmost segment comes first in logical order
                body_parts.sort(key=lambda p: -p[0])
                visual_text = " ".join(t for _, t in sorted(body_parts, key=lambda p: p[0]))
                raw_rows.append((row[0]["top"], margin_no, visual_text))
            logical = [(_top, no, _to_logical(t)) for _top, no, t in raw_rows]
            # page-level sanity check: if the repaired page still scores as
            # reversed, the PDF stored logical order already → undo.
            score_fixed = sum(hebrew.order_score(t) for _, _, t in logical)
            score_raw = sum(hebrew.order_score(t) for _, _, t in raw_rows)
            if score_raw > score_fixed:
                logical = raw_rows
            else:
                pt.visual_order_fixed = True
            numbered = [no for _, no, _ in logical if no is not None]
            pt.printed_line_numbers = _looks_like_line_numbers(numbered)
            synth = 0
            for top, no, text in logical:
                if not text and no is None:
                    continue
                synth += 1
                line_no = no if (pt.printed_line_numbers and no is not None) else None
                line = Line(page=idx, line_no=line_no or 0, text=text, synthetic=line_no is None, top=float(top))
                line._margin_no = no  # type: ignore[attr-defined]
                pt.lines.append(line)
            _assign_missing_numbers(pt)
            pages.append(pt)
    return pages


def _harmonize_line_numbers(pages: list[PageText]) -> None:
    """Short pages (e.g. the last page) have too few numbers to decide on
    their own; if most pages carry printed numbers, accept a short page whose
    numbers are strictly sequential from 1."""
    with_lines = [p for p in pages if p.lines]
    if not with_lines:
        return
    printed = sum(1 for p in with_lines if p.printed_line_numbers)
    if printed < max(1, len(with_lines) // 2):
        return
    for p in with_lines:
        if p.printed_line_numbers or p.method != "text":
            continue
        nums = [ln._margin_no for ln in p.lines if getattr(ln, "_margin_no", None) is not None]
        if nums and nums == list(range(nums[0], nums[0] + len(nums))) and nums[0] <= 3:
            p.printed_line_numbers = True
            for ln in p.lines:
                mn = getattr(ln, "_margin_no", None)
                ln.line_no = mn if mn is not None else 0
                ln.synthetic = mn is None
            _assign_missing_numbers(p)


def _looks_like_line_numbers(nums: list[int]) -> bool:
    if len(nums) < 5:
        return False
    increasing = sum(1 for a, b in zip(nums, nums[1:]) if b == a + 1)
    return increasing >= 0.8 * (len(nums) - 1) and nums[0] <= 3


def _assign_missing_numbers(pt: PageText) -> None:
    """Lines without a printed number (headers, wrapped text) get a number
    derived from their neighbours; a page with no printed numbers is fully
    synthetic and numbered 1..n."""
    if not pt.printed_line_numbers:
        for i, ln in enumerate(pt.lines, start=1):
            ln.line_no = i
            ln.synthetic = True
        return
    last = 0
    for ln in pt.lines:
        if ln.line_no:
            last = ln.line_no
        else:
            # unnumbered line (header/footer or continuation). It shares the
            # previous printed number; marked synthetic so the UI can say so.
            ln.line_no = max(last, 1)
            ln.synthetic = True


def ocr_page(data: bytes, page_no: int, langs: str = "heb+eng", dpi: int = 300) -> PageText:
    """OCR a single page. Requires the tesseract binary with Hebrew data."""
    import pypdfium2 as pdfium
    import pytesseract

    pdf = pdfium.PdfDocument(data)
    try:
        page = pdf[page_no - 1]
        image = page.render(scale=dpi / 72).to_pil()
    finally:
        pdf.close()
    out = pytesseract.image_to_data(image, lang=langs, output_type=pytesseract.Output.DICT, config="--psm 4")
    rows: dict[tuple[int, int, int], list[tuple[int, str]]] = {}
    tops: dict[tuple[int, int, int], int] = {}
    for i, word in enumerate(out["text"]):
        if not word or not word.strip():
            continue
        key = (out["block_num"][i], out["par_num"][i], out["line_num"][i])
        rows.setdefault(key, []).append((out["left"][i], word))
        tops.setdefault(key, out["top"][i])
    pt = PageText(page=page_no, method="ocr")
    width = image.width
    numbered = []
    entries = []
    for key in sorted(rows, key=lambda k: tops[k]):
        words = rows[key]
        margin_no = None
        body = []
        for left, w in words:
            if _NUM_RE.match(w) and (left < width * 0.1 or left > width * 0.88):
                margin_no = int(w)
            else:
                body.append((left, w))
        # tesseract returns words in logical order for RTL scripts per line;
        # order by x descending for Hebrew-dominant lines.
        text = " ".join(w for _, w in sorted(body, key=lambda p: -p[0])) if hebrew.hebrew_ratio(" ".join(w for _, w in body)) >= 0.3 else " ".join(w for _, w in sorted(body))
        entries.append((tops[key], margin_no, text))
        if margin_no is not None:
            numbered.append(margin_no)
    pt.printed_line_numbers = _looks_like_line_numbers(numbered)
    for top, no, text in entries:
        if not text:
            continue
        pt.lines.append(Line(page=page_no, line_no=no if (pt.printed_line_numbers and no) else 0, text=text, top=float(top)))
    pt.char_count = sum(len(ln.text) for ln in pt.lines)
    _assign_missing_numbers(pt)
    for ln in pt.lines:
        ln.synthetic = True if not pt.printed_line_numbers else ln.synthetic
    return pt


def tesseract_available(langs: str = "heb") -> bool:
    try:
        import pytesseract

        have = set(pytesseract.get_languages(config=""))
        return all(lang in have for lang in langs.split("+"))
    except Exception:  # noqa: BLE001
        return False


def extract_document(data: bytes, *, allow_ocr: bool = True, ocr_langs: str = "heb+eng") -> ExtractedDocument:
    pages = extract_text_layer(data)
    warnings: list[str] = []
    for i, pt in enumerate(pages):
        if pt.method == "empty":
            if allow_ocr and tesseract_available(ocr_langs):
                pages[i] = ocr_page(data, pt.page, ocr_langs)
            else:
                warnings.append(f"page {pt.page}: no text layer and OCR unavailable")
    _harmonize_line_numbers(pages)
    if _fix_bracket_orientation(pages):
        warnings.append("bracket glyphs were stored mirrored; orientation repaired for the whole document")
    _tag_headers_footers(pages)
    return ExtractedDocument(pages=pages, page_count=len(pages), warnings=warnings)


_BRACKET_SWAP = str.maketrans("()[]{}<>", ")(][}{><")
_OK_PAIR_RE = re.compile(r"\([^()\n]{1,80}\)")
_BAD_PAIR_RE = re.compile(r"\)[^()\n]{1,80}\(")


def _fix_bracket_orientation(pages: list[PageText]) -> bool:
    """Some exporters store RTL brackets as their mirrored glyphs, so after the
    visual→logical repair "(הפסקה)" comes out as ")הפסקה(". Decide once per
    document from paired brackets and swap back if mirrored pairs dominate."""
    texts = [ln.text for p in pages if p.method == "text" for ln in p.lines]
    # Net-HaMishpat anchors "<#n#>" are a second, unambiguous orientation signal
    good = sum(len(_OK_PAIR_RE.findall(t)) + len(re.findall(r"<#\d+#>", t)) for t in texts)
    bad = sum(len(_BAD_PAIR_RE.findall(t)) + len(re.findall(r">#\d+#<", t)) for t in texts)
    if bad >= 2 and bad > 2 * good:
        for p in pages:
            if p.method != "text":
                continue
            for ln in p.lines:
                ln.text = ln.text.translate(_BRACKET_SWAP)
        return True
    return False


_PAGE_NO_RE = re.compile(r"^(?:עמוד\s*)?\d{1,4}(?:\s*(?:מתוך|/)\s*\d{1,4})?$|^-\s*\d{1,4}\s*-$")


def _tag_headers_footers(pages: list[PageText]) -> None:
    """Lines repeated at the top/bottom of most pages are page furniture."""
    if len(pages) < 3:
        for p in pages:
            for ln in p.lines:
                if _PAGE_NO_RE.match(ln.text.strip()):
                    ln.kind = "footer"
        return
    key = lambda t: re.sub(r"\d+", "#", hebrew.normalize(t))  # noqa: E731
    top_counts: Counter[str] = Counter()
    bottom_counts: Counter[str] = Counter()
    for p in pages:
        for ln in p.lines[:3]:
            top_counts[key(ln.text)] += 1
        for ln in p.lines[-3:]:
            bottom_counts[key(ln.text)] += 1
    threshold = max(2, int(len([p for p in pages if p.lines]) * 0.6))
    headers = {k for k, c in top_counts.items() if c >= threshold and k}
    footers = {k for k, c in bottom_counts.items() if c >= threshold and k}
    for p in pages:
        for i, ln in enumerate(p.lines):
            k = key(ln.text)
            if i < 3 and k in headers:
                ln.kind = "header"
            elif i >= len(p.lines) - 3 and (k in footers or _PAGE_NO_RE.match(ln.text.strip())):
                ln.kind = "footer"
