# Per-cell uid probes ([2026] VJS-CC-VJS 7 J7 and J9)

These run INSIDE a container, as the cell or as the privileged driver, under the
granted posture. They are deliberately plain, dependency-free scripts: the J7
probe runs as a cell that has already dropped to its own uid and holds no
capabilities, so it must work with nothing but the standard library and must not
import anything from the repo.

`test_per_cell_uid_gates.py` drives them and asserts on their output.

They are excluded from ruff because they are executed by `python3 -c`-style entry
inside a container rather than imported, and the compact style (semicolons, short
names) is deliberate: every line of a probe that runs as the attacker should fit
on screen next to the property it is testing.
