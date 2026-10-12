import pdfplumber, subprocess, json, re, sys
PDF = sys.argv[1] if len(sys.argv) > 1 else '315 - full list - V3.pdf'  # Project 315's table
CLEAN = re.compile('[‎‏‪-‮⁦-⁩]')
def cell_text(pno, bbox, scale=1.0):
    x0, top, x1, bottom = bbox
    out = subprocess.run(['pdftotext', '-f', str(pno), '-l', str(pno), '-x', str(int(x0)), '-y', str(int(top)), '-W', str(int(x1 - x0) + 1),
                          '-H', str(int(bottom - top) + 1), '-r', '72', PDF, '-'], capture_output=True, text=True).stdout
    return CLEAN.sub('', out).replace('\f', '').strip()
rows = []
with pdfplumber.open(PDF) as pdf:
    for pi, page in enumerate(pdf.pages, 1):
        for tb in page.find_tables():
            for r in tb.rows:
                cells = r.cells
                if len(cells) != 6 or any(c is None for c in cells):
                    continue
                vals = [cell_text(pi, c) for c in cells]
                cls, inv, exc, met, desc, num = vals
                if not num.strip().isdigit():
                    continue
                rows.append({'n': int(num), 'page': pi, 'met': met, 'exceptional': exc, 'involved': inv, 'class': ' '.join(cls.split()), 'desc': desc})
json.dump(rows, open('315.json', 'w'), ensure_ascii=False, indent=1)
print(len(rows), rows[0], rows[-1]['n'])
