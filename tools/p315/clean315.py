import json, re, collections
rows = json.load(open('315.json'))
def fixp(s):
    s = s.translate(str.maketrans('()', ')('))
    s = re.sub(r'(?<=\S)\s+([.,:;])(?=\S)', r'\1 ', s)   # "x .y" -> "x. y"
    s = re.sub(r'^\.(\d+)\s*', r'\1. ', s)                 # ".1אירוע" -> "1. אירוע"
    s = re.sub(r'\s+([.,])$', r'\1', s)
    return s
DATE = re.compile(r'(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})(?!\d)')
out = []
for r in rows:
    lines = [fixp(l.strip()) for l in r['desc'].split('\n') if l.strip()]
    head = lines[0] if lines else ''
    text = ' '.join(lines[1:]) if len(lines) > 1 else ''
    ds = DATE.findall(head)
    dates = ['%s-%02d-%02d' % (y if len(y) == 4 else '20' + y, int(m), int(d)) for d, m, y in ds]
    out.append({'n': r['n'], 'date_from': dates[0] if dates else None, 'date_to': dates[-1] if dates else None, 'head': head,
                'text': text, 'met': r['met'], 'exceptional': r['exceptional'], 'involved': r['involved'], 'class': fixp(r['class'])})
json.dump(out, open('315-clean.json', 'w'), ensure_ascii=False, indent=1)
print(collections.Counter(x['class'] for x in out))
print(collections.Counter((x['met'], x['exceptional'], x['involved']) for x in out).most_common(12))
print(collections.Counter((x['date_from'] or '????')[:4] for x in out))
print(sum(1 for x in out if not x['date_from']), 'no date')
for x in out[16:19]: print(json.dumps(x, ensure_ascii=False)[:500])
