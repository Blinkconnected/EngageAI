"""Every relative link in the documentation must point at something.

A narrower check than it first looks, and deliberately so. An earlier
attempt verified every backtick-quoted filename in `docs/` and had to be
thrown away: it flagged `domain/audit.py` in `event-bus.md`, which is an
accurate statement about what M9 introduced before M10 superseded it,
and it flagged design documents naming modules nobody has written yet.
A guard that fails on true history pushes people to falsify it, and a
guard that fails on design documents pushes people to delete the guard.

A link is different. `[FAQ](./faq.md)` pointing at a file that is not
there is wrong in every context — there is no historical or
design-stage reading in which a reader clicking it gets what they were
promised. That is the defect this catches: the architecture index linked
`faq.md` for three days while the file itself was not in git.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS = REPO_ROOT / "docs"

#: `[text](target)`. Angle-bracket and reference-style links are not
#: used anywhere in these documents; if that changes, this needs to.
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _is_relative(target: str) -> bool:
    return not target.startswith(("http://", "https://", "mailto:", "#"))


def test_every_relative_documentation_link_resolves() -> None:
    broken: list[str] = []

    for doc in sorted(DOCS.rglob("*.md")):
        for target in LINK.findall(doc.read_text(encoding="utf-8")):
            if not _is_relative(target):
                continue
            # `file.md#section` — the anchor is not checked, only that
            # the document it lives in exists.
            path = target.split("#", 1)[0]
            if not path:
                continue
            resolved = (doc.parent / path).resolve()
            if not resolved.exists():
                broken.append(f"  {doc.relative_to(REPO_ROOT)} -> {target}")

    assert not broken, "documentation links that go nowhere:\n" + "\n".join(sorted(broken))
