#!/usr/bin/env python3
"""Assemble the Boltrig brownfield corpus into one printable PDF."""
import re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
C = HERE.parent            # the corpus is this script's parent directory
PANDOC_FROM = ('markdown+raw_html+pipe_tables-smart-yaml_metadata_block'
               '-tex_math_dollars-tex_math_single_backslash-tex_math_double_backslash-raw_tex')

def split_front(t):
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', t, re.S)
    if not m: return {}, t
    fm = {}
    for line in m.group(1).splitlines():
        if ':' in line:
            k, v = line.split(':', 1); fm[k.strip()] = v.strip().strip('"')
    return fm, t[m.end():]

def load(rel):
    fm, body = split_front((C / rel).read_text(errors='replace'))
    m = re.match(r'^\s*#\s+(.+?)\s*\n', body)
    title = None
    if m: title, body = m.group(1), body[m.end():]
    if not title: title = fm.get('area') or Path(rel).stem
    return fm, title, body.strip()

order = [('part', 'Part I', 'The corpus',
          'What Boltrig is, what was measured, how far the corpus reaches, and what is dangerous.')]
order += [('doc', d) for d in ['BIBLE.md', 'REFERENT.md', 'COVERAGE.md', 'RISK-REGISTER.md', 'GAPS.md']]
order += [('part', 'Part II', 'The twenty area specifications',
           'One area per chapter, every chapter written against the same pinned commit.')]
order += [('doc', f'specs/{p.name}') for p in sorted(C.glob('specs/SPEC-*.md'))]
order += [('part', 'Part III', 'Appendices', 'How the corpus was written, and the evidence behind it.')]
order += [('doc', d) for d in ['AUTHORING-CONTRACT.md', 'evidence/orchestrator-findings.md',
                               'evidence/worker-ui-route-inventory.md']]

buf, nch = [], 0
for row in order:
    if row[0] == 'part':
        _, kick, title, blurb = row
        pid = kick.lower().replace(' ', '-')
        buf.append(f'\n\n<div class="partsep" id="{pid}">\n<div class="part-kicker">{kick}</div>\n'
                   f'<div class="part-title">{title}</div>\n<div class="part-blurb">{blurb}</div>\n</div>\n')
        continue
    rel = row[1]
    fm, title, body = load(rel)
    nch += 1
    cid = 'ch-' + re.sub(r'[^a-z0-9]+', '-', rel.lower()).strip('-')
    m = re.match(r'^SPEC-?\s?(\d+)', Path(rel).stem)
    kicker = f'Area {m.group(1)}' if (m and rel.startswith('specs/')) else ''
    if kicker: title = re.sub(r'^SPEC[- ]?\d+:?\s*', '', title)
    meta = f'<div class="chapmeta">{fm["id-block"]}</div>' if fm.get('id-block') else ''
    kick_html = f'<div class="chapkicker">{kicker}</div>' if kicker else ''
    buf.append(f'\n\n<div class="chapter" id="{cid}">{kick_html}<h1>{title}</h1>{meta}</div>\n\n')
    buf.append(body + "\n")

(HERE / 'corpus.md').write_text("\n".join(buf))
print(f"assembled {nch} chapters")

subprocess.run(['pandoc', str(HERE / 'corpus.md'), '-f', PANDOC_FROM, '-t', 'html5',
                '--no-highlight', '-o', str(HERE / 'body.html')],
               check=True, capture_output=True)
body = (HERE / 'body.html').read_text(errors='replace')

def clean(s): return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', s)).strip()

# Find each chapter/part by its opening tag, then read a WINDOW after it. Matching
# to the first </div> was wrong: these blocks contain nested divs, so the window
# closed on the kicker and every chapter fell back to showing its raw id.
toc = []
for m in re.finditer(r'<div\b[^>]*\bid="([^"]+)"[^>]*>|<h2\b[^>]*\bid="([^"]+)"[^>]*>(.*?)</h2>', body, re.S):
    if m.group(2):
        toc.append(('l2', m.group(2), clean(m.group(3)), '')); continue
    tag = m.group(0)
    if 'partsep' not in tag and 'chapter' not in tag: continue
    win = body[m.end():m.end() + 900]
    if 'partsep' in tag:
        k = re.search(r'part-kicker">(.*?)</div>', win, re.S)
        t = re.search(r'part-title">(.*?)</div>', win, re.S)
        toc.append(('part', m.group(1), f'{clean(k.group(1)) if k else ""} &nbsp; {clean(t.group(1)) if t else ""}', ''))
    else:
        h = re.search(r'<h1[^>]*>(.*?)</h1>', win, re.S)
        kk = re.search(r'chapkicker">(.*?)</div>', win, re.S)
        toc.append(('l1', m.group(1), clean(h.group(1)) if h else m.group(1), clean(kk.group(1)) if kk else ''))

items = []
for kind, tid, txt, kick in toc:
    if kind == 'part':
        items.append(f'<li class="part"><a href="#{tid}">{txt}</a></li>')
    elif kind == 'l1':
        k = f'<span class="k">{kick} &middot; </span>' if kick else ''
        items.append(f'<li class="l1"><a href="#{tid}">{k}{txt}</a></li>')
    else:
        items.append(f'<li class="l2"><a href="#{tid}">{txt}</a></li>')

cover = '''<div class="cover"><div><div class="rule"></div><h1>Boltrig</h1>
<div class="sub">A brownfield specification<br>of the system as built</div></div><div>
<div class="stats">
<div class="stat"><span class="n">20</span><span class="l">area specifications</span></div>
<div class="stat"><span class="n">1,902</span><span class="l">requirement rows</span></div>
<div class="stat"><span class="n">6,151</span><span class="l">verified citations</span></div>
<div class="stat"><span class="n">40/56</span><span class="l">findings confirmed</span></div></div>
<div class="pin">referent &nbsp; <b>19bcae7fa81663fe8998377c86451ba08fb16e48</b><br>
branch &nbsp;&nbsp;&nbsp; origin/main &nbsp;&middot;&nbsp; github.com/wlilley93/boltrig<br>
captured &nbsp; 2026-08-24</div></div></div>'''

head = ('<!doctype html><html lang="en-GB"><head><meta charset="utf-8">'
        '<title>Boltrig, a brownfield specification</title>'
        '<style>html{string-set:booktitle "Boltrig, as built";}</style>'
        '<link rel="stylesheet" href="print.css"></head><body>')
(HERE / 'doc.html').write_text(head + cover +
    '<div class="toc"><h2>Contents</h2><ol>' + "\n".join(items) + '</ol></div>' + body + '</body></html>')
print(f"toc: {sum(1 for k,*_ in toc if k=='part')} parts, "
      f"{sum(1 for k,*_ in toc if k=='l1')} chapters, {sum(1 for k,*_ in toc if k=='l2')} sections")
