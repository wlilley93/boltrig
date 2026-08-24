# Building the PDFs

Two documents come out of this corpus:

    build.py       the full specification, every chapter, ~804 pages
    build_reqs.py  the requirements alone, status stripped, ~100 pages

Both read the corpus from this script's parent directory and write HTML beside
themselves; WeasyPrint turns that into the PDF. WeasyPrint is not a dependency
of Boltrig and is deliberately not added to any lockfile here:

    python3 -m venv /tmp/pdfenv && /tmp/pdfenv/bin/pip install weasyprint
    python3 build.py      && /tmp/pdfenv/bin/weasyprint -e utf-8 doc.html  Boltrig-Brownfield-Specification.pdf
    python3 build_reqs.py && /tmp/pdfenv/bin/weasyprint -e utf-8 reqs.html Boltrig-Requirements.pdf

`print.css` carries the page geometry, running heads and the contents styling;
`reqs.css` adds only what the requirements document needs on top of it.

Fonts are DejaVu Serif, IBM Plex Sans and JetBrains Mono, all resolved from the
system. If a face is missing the page still sets, in a fallback, silently: check
the output rather than trusting a clean exit.
