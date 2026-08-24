#!/usr/bin/env python3
"""Extract the requirement statements alone into a standalone specification.

The register carries a status column (IMPLEMENTED, DEAD, SCAFFOLDED ...). This
document drops it: each entry states what the system does, with no claim about
how well it is tested.

Dropping status is not free. Rows tagged DEAD or SCAFFOLDED do not state a
requirement, they state a finding about dead code ("ChiefOfStaff is present in
the tree but constructed by no production composition root"). Stripped of their
tag those would read as things the system is REQUIRED to do, which is the
opposite of what they mean. They are excluded here and listed in the appendix so
nothing goes missing quietly.
"""
import csv, html, re, subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
C = HERE.parent            # the corpus is this script's parent directory

KEEP = {'IMPLEMENTED', 'IMPLEMENTED-UNTESTED'}
# Statements that assert an ABSENCE of test or gate coverage are findings about
# the governance layer, not requirements of the system.
FINDINGS = {'BT-REQ-0588', 'BT-REQ-1937'}

rows = list(csv.DictReader((C / 'registers/requirements.tsv').open(), delimiter='\t'))
kept = [r for r in rows if r['status'] in KEEP and r['id'] not in FINDINGS]
dropped = [r for r in rows if r not in kept]

# area number -> human title, taken from each spec's own front matter or h1
titles = {}
for p in sorted(C.glob('specs/SPEC-*.md')):
    num = re.match(r'SPEC-(\d+)', p.stem).group(1)
    t = p.read_text(errors='replace')
    m = re.search(r'^area:\s*"?(.+?)"?\s*$', t, re.M)
    if m:
        titles[num] = re.sub(r'^\d+\s+', '', m.group(1))
    else:
        h = re.search(r'^#\s+(?:SPEC[- ]?\d+:?\s*)?(.+)$', t, re.M)
        titles[num] = h.group(1).strip() if h else p.stem

def area_of(r):
    m = re.match(r'SPEC-(\d+)', r['area']); return m.group(1) if m else '??'

def fmt(s):
    """Escape, then restore `code` spans."""
    s = html.escape(s.strip())
    return re.sub(r'`([^`]+)`', r'<code>\1</code>', s)

groups = {}
for r in kept:
    groups.setdefault(area_of(r), []).append(r)

body = []
for num in sorted(groups):
    rs = groups[num]
    body.append(f'<div class="chapter" id="a{num}"><div class="chapkicker">Area {num}</div>'
                f'<h1>{html.escape(titles.get(num, ""))}</h1>'
                f'<div class="chapmeta">{len(rs)} requirements</div></div>')
    body.append('<div class="reqs">')
    for r in rs:
        body.append(f'<div class="req"><span class="rid">{r["id"].replace("BT-REQ-","")}</span>{fmt(r["statement"])}</div>')
    body.append('</div>')

# appendix: what was excluded, and why
body.append('<div class="chapter" id="excluded"><h1>Excluded rows</h1>'
            f'<div class="chapmeta">{len(dropped)} of {len(rows)} register rows</div></div>')
body.append('<p>These rows are in the register but are not requirements. A row tagged '
            'DEAD or SCAFFOLDED records that something in the tree is unreachable or '
            'unfinished; with its tag removed it would read as an instruction to build '
            'exactly that. A SEAM row names an external system that supplies the behaviour '
            'rather than stating behaviour of this one. They are listed so the omission is '
            'visible and reversible.</p>')
reasons = {'DEAD': 'unreachable in the tree', 'SCAFFOLDED': 'shape without a body',
           'SEAM': 'supplied by an external system', 'UNCERTAIN': 'not settled by the author'}
for st in ['DEAD', 'SCAFFOLDED', 'SEAM', 'UNCERTAIN']:
    grp = [r for r in dropped if r['status'] == st]
    if not grp: continue
    body.append(f'<h2>{st.title()} &middot; {reasons[st]} ({len(grp)})</h2><div class="reqs">')
    for r in grp:
        body.append(f'<div class="req"><span class="rid">{r["id"].replace("BT-REQ-","")}</span>{fmt(r["statement"])}</div>')
    body.append('</div>')
grp = [r for r in dropped if r['id'] in FINDINGS]
if grp:
    body.append(f'<h2>Findings about the governance layer ({len(grp)})</h2><div class="reqs">')
    for r in grp:
        body.append(f'<div class="req"><span class="rid">{r["id"].replace("BT-REQ-","")}</span>{fmt(r["statement"])}</div>')
    body.append('</div>')
body_html = "\n".join(body)

toc = "\n".join(
    f'<li class="l1"><a href="#a{n}"><span class="k">Area {n} &middot; </span>'
    f'{html.escape(titles.get(n,""))}<span class="cnt">{len(groups[n])}</span></a></li>'
    for n in sorted(groups))
toc += f'<li class="l1"><a href="#excluded">Excluded rows<span class="cnt">{len(dropped)}</span></a></li>'

cover = f'''<div class="cover"><div><div class="rule"></div><h1>Boltrig</h1>
<div class="sub">Requirements</div></div><div>
<div class="stats">
<div class="stat"><span class="n">{len(kept):,}</span><span class="l">requirements</span></div>
<div class="stat"><span class="n">{len(groups)}</span><span class="l">areas</span></div>
<div class="stat"><span class="n">{len(dropped)}</span><span class="l">rows excluded</span></div></div>
<div class="pin">referent &nbsp; <b>19bcae7fa81663fe8998377c86451ba08fb16e48</b><br>
branch &nbsp;&nbsp;&nbsp; origin/main &nbsp;&middot;&nbsp; github.com/wlilley93/boltrig<br>
captured &nbsp; 2026-08-24</div></div></div>'''

note = f'''<div class="note"><h2>What this is</h2>
<p>Every requirement Boltrig satisfies at the pinned commit, stated once, with nothing
said about how it was verified. The full corpus records a status against each row
(IMPLEMENTED, IMPLEMENTED-UNTESTED, DEAD, SCAFFOLDED, SEAM) together with a
<code>path:line</code> citation and its bound invariant. None of that appears here. This
document answers only one question: what does the system do.</p>
<p>{len(kept):,} of the register's {len(rows):,} rows are reproduced. The {len(dropped)}
that are not do not state requirements, and stripped of their status tag they would
read as though they did. They are reproduced in full in the final chapter rather than
dropped in silence.</p>
<p>Statements are as written in the corpus. They are descriptive present tense rather
than <i>shall</i> form, and each one traces to a citation in the full specification
under the same identifier.</p></div>'''

head = ('<!doctype html><html lang="en-GB"><head><meta charset="utf-8">'
        '<title>Boltrig requirements</title>'
        '<style>html{string-set:booktitle "Boltrig, requirements";}</style>'
        '<link rel="stylesheet" href="print.css"><link rel="stylesheet" href="reqs.css"></head><body>')
(HERE / 'reqs.html').write_text(
    head + cover + note +
    '<div class="toc"><h2>Contents</h2><ol>' + toc + '</ol></div>' +
    body_html + '</body></html>')
print(f"{len(kept)} requirements across {len(groups)} areas; {len(dropped)} excluded")
