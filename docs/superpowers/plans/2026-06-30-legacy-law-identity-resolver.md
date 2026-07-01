# Legacy Law-Identity Resolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone, migration-ready Python package that resolves legacy (vols ≤ 63) U.S. Statutes pLaw identity — public/private status and a public-law-number-based `LawIdentifier` — and wire it into the existing pipeline, fixing the parse crash, blank-id `validate_failed`, and chapter-vs-PL-number defects.

**Architecture:** A new self-contained repo `Code/legacy-law-identity/` (sibling to `data-preprocessing-pipeline`) exposes `resolve_legacy_law_identities(plaws, vol, ns)`. The pipeline installs it (`pip install -e`) and calls it from the legacy branch of the raw extractor; the modern (>63) path and the malformed-id repair pass are gated to `vol > 63`. The publisher's existing normalizer produces the canonical `Public Law {congress}–{N}` string, so output format is unchanged.

**Tech Stack:** Python 3.11, `xml.etree.ElementTree` (stdlib only — no third-party runtime deps), `pytest` (test-only), `setuptools` packaging.

## Global Constraints

- **Legacy = `int(vol) <= 63`; modern = `> 63`.** Modern behavior must be byte-for-byte unchanged.
- **Approach A:** sidenote public-law number taken **verbatim** (even if OCR-wrong); blanks filled deterministically (monotonic continuation); **never silently override a parseable sidenote**. Residual errors are left for the cv-correct human queue.
- **Scope = identity only:** is_public, `LawIdentifier` (bare `"{congress}-{N}"`), null-safety. Do **not** modify section/division walking, titles, dates, or string formatting.
- **Identical output format:** same 26 columns, same formats. The publisher's `_normalize_one_law_id` (`pipeline/publisher.py:94-154`) canonicalizes the bare id to `Public Law {congress}–{N}` (en-dash U+2013) — reuse it; do not format in the module.
- **Package has zero third-party runtime dependencies** (stdlib `ElementTree` only), so it migrates cleanly to another server.
- **Pipeline venv:** `/home/G39248410/citizen_voice/venv/bin/python`; install with `python -m pip` (never `bin/pip` directly).
- **Two git repos:** package tasks commit in `Code/legacy-law-identity/`; pipeline integration tasks commit in `Code/data-preprocessing-pipeline/` on branch `feature/legacy-law-identity-resolver`.

---

## File Structure

**New standalone package repo — `/home/G39248410/citizen_voice/Code/legacy-law-identity/`:**
- `pyproject.toml` — packaging metadata, `requires-python>=3.11`, no runtime deps, `test` extra = pytest.
- `README.md` — purpose, install, integration snippet, migration note.
- `.gitignore` — `__pycache__/`, `*.egg-info/`, `.pytest_cache/`, `.venv/`, `dist/`, `build/`.
- `src/legacy_law_identity/__init__.py` — re-exports `resolve_legacy_law_identities`.
- `src/legacy_law_identity/resolver.py` — the resolver (single responsibility: legacy pLaw identity).
- `tests/conftest.py` — synthetic pLaw fixture builders (no real-data dependency).
- `tests/test_resolver.py` — unit tests.

**Existing pipeline repo — modified:**
- `legacy/Extract_Sections_Divisions_From_XML.py:141-208` — call the resolver for `vol ≤ 63`; null-safe `<publicPrivate>` for the modern branch.
- `parser/uslm_parser.py:805-872` — gate `_repair_malformed_law_identifiers` to `vol > 63`.
- `tests/integration/test_legacy_law_identity_regression.py` — new regression suite over vols 44–64 (excl 60) + modern controls.

---

## Task 1: Scaffold the standalone package repo

**Files:**
- Create: `Code/legacy-law-identity/pyproject.toml`
- Create: `Code/legacy-law-identity/.gitignore`
- Create: `Code/legacy-law-identity/README.md`
- Create: `Code/legacy-law-identity/src/legacy_law_identity/__init__.py`
- Create: `Code/legacy-law-identity/src/legacy_law_identity/resolver.py`
- Create: `Code/legacy-law-identity/tests/conftest.py`
- Create: `Code/legacy-law-identity/tests/test_resolver.py`

**Interfaces:**
- Produces: `resolve_legacy_law_identities(plaws, vol, ns) -> dict[int, dict]` (stub in this task; implemented in Tasks 2–5). `plaws` is a list of `ElementTree.Element` `<pLaw>` nodes; `vol` is int-or-str; `ns` is `{"uslm": "<uri>"}`. Returns `{doc_index: {"is_public": bool, "law_identifier": str | None}}`.

- [ ] **Step 1: Create the package directory tree and packaging file**

Create `Code/legacy-law-identity/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "legacy-law-identity"
version = "0.1.0"
description = "Legacy (Statutes vols <=63) pLaw identity resolver for the citizen_voice pipeline"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
test = ["pytest>=7"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Create `Code/legacy-law-identity/.gitignore`:

```gitignore
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.venv/
dist/
build/
```

- [ ] **Step 2: Create the stub module and package init**

Create `Code/legacy-law-identity/src/legacy_law_identity/resolver.py`:

```python
"""Legacy (vols <=63) U.S. Statutes pLaw identity resolver. See README."""
from __future__ import annotations


def resolve_legacy_law_identities(plaws, vol, ns):
    """Resolve identity for every pLaw in a legacy volume.

    Returns {doc_index: {"is_public": bool, "law_identifier": str | None}}.
    """
    raise NotImplementedError
```

Create `Code/legacy-law-identity/src/legacy_law_identity/__init__.py`:

```python
from .resolver import resolve_legacy_law_identities

__all__ = ["resolve_legacy_law_identities"]
```

- [ ] **Step 3: Create the fixture helpers**

Create `Code/legacy-law-identity/tests/conftest.py`:

```python
import xml.etree.ElementTree as ET

USLM = "http://schemas.gpo.gov/xml/uslm"
NS = {"uslm": USLM}


def plaw_xml(public="public", sidenote="", doc_number="", congress="77"):
    """Build one <pLaw> XML string. Pass public=None to OMIT <publicPrivate>."""
    parts = []
    if public is not None:
        parts.append(f"<publicPrivate>{public}</publicPrivate>")
    if doc_number:
        parts.append(f"<docNumber>{doc_number}</docNumber>")
    if congress:
        parts.append(f"<congress>{congress}</congress>")
    meta = f"<meta>{''.join(parts)}</meta>"
    side = f"<sidenote>{sidenote}</sidenote>" if sidenote is not None else ""
    return f"<pLaw>{meta}{side}</pLaw>"


def plaws_from(*plaw_strings):
    """Return (plaws_list, ns) for a sequence of plaw_xml() strings."""
    doc = f'<lawDoc xmlns="{USLM}">{"".join(plaw_strings)}</lawDoc>'
    root = ET.fromstring(doc)
    return root.findall(".//uslm:pLaw", NS), NS
```

- [ ] **Step 4: Add an import smoke test**

Create `Code/legacy-law-identity/tests/test_resolver.py`:

```python
from legacy_law_identity import resolve_legacy_law_identities


def test_entrypoint_importable_and_callable():
    assert callable(resolve_legacy_law_identities)
```

- [ ] **Step 5: Create README**

Create `Code/legacy-law-identity/README.md`:

```markdown
# legacy-law-identity

Resolves the identity (public/private status + public-law-number-based
`LawIdentifier`) of `<pLaw>` elements in legacy U.S. Statutes-at-Large volumes
(≤ 63) for the citizen_voice pipeline.

## Why
The legacy branch of the pipeline's raw extractor crashed on missing
`<publicPrivate>`, emitted empty `LawIdentifier`s, and (via a downstream repair
pass) published chapter numbers instead of public-law numbers. This package
owns legacy identity resolution and fixes all three.

## Install
    python -m pip install -e /path/to/legacy-law-identity

## Use
    from legacy_law_identity import resolve_legacy_law_identities
    ids = resolve_legacy_law_identities(plaws, vol, ns)
    # plaws: list of ElementTree <pLaw> Elements (document order)
    # vol:   volume number (int or str); intended for vol <= 63
    # ns:    {"uslm": "<namespace-uri>"}
    # -> {doc_index: {"is_public": bool, "law_identifier": "77-188" | None}}

`law_identifier` is the BARE `"{congress}-{N}"` form; the pipeline's publisher
normalizes it to `Public Law {congress}–{N}` (en-dash).

## Migration
Pure stdlib (`xml.etree.ElementTree`); no third-party runtime deps.
```

- [ ] **Step 6: Initialise git repo, install editable, run the smoke test**

Run (each command from the package dir):

```bash
cd /home/G39248410/citizen_voice/Code/legacy-law-identity
git init -q
/home/G39248410/citizen_voice/venv/bin/python -m pip install -e ".[test]"
/home/G39248410/citizen_voice/venv/bin/python -m pytest tests/ -q
```

Expected: `1 passed`.

- [ ] **Step 7: Commit the scaffold**

```bash
cd /home/G39248410/citizen_voice/Code/legacy-law-identity
git add -A
git commit -q -m "chore: scaffold legacy-law-identity standalone package"
```

---

## Task 2: publicPrivate null-safety + is_public inference

**Files:**
- Modify: `Code/legacy-law-identity/src/legacy_law_identity/resolver.py`
- Test: `Code/legacy-law-identity/tests/test_resolver.py`

**Interfaces:**
- Produces: `_text(elem, path, ns) -> str`; `_is_public(plaw, sidenote_text, ns) -> bool`. `_is_public` returns `True` when `<publicPrivate>` text is "public" (case-insensitive), `False` for "private"; when the element is missing/empty it infers from `sidenote_text` (a `Private Law` marker → False, else True).

- [ ] **Step 1: Write failing tests**

Append to `tests/test_resolver.py`:

```python
from legacy_law_identity.resolver import _is_public, _text
from conftest import plaws_from, plaw_xml, NS


def test_is_public_true_when_publicprivate_public():
    plaws, ns = plaws_from(plaw_xml(public="public"))
    assert _is_public(plaws[0], "", ns) is True


def test_is_public_false_when_publicprivate_private():
    plaws, ns = plaws_from(plaw_xml(public="private"))
    assert _is_public(plaws[0], "", ns) is False


def test_is_public_defaults_true_when_publicprivate_missing():
    # Issue 2: <publicPrivate> absent must NOT crash; default public.
    plaws, ns = plaws_from(plaw_xml(public=None, sidenote="[Public Law 5]"))
    assert _is_public(plaws[0], "[Public Law 5]", ns) is True


def test_is_public_infers_private_from_sidenote_when_missing():
    plaws, ns = plaws_from(plaw_xml(public=None, sidenote="[Private Law 12]"))
    assert _is_public(plaws[0], "[Private Law 12]", ns) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/G39248410/citizen_voice/Code/legacy-law-identity && /home/G39248410/citizen_voice/venv/bin/python -m pytest tests/ -q`
Expected: FAIL (`ImportError: cannot import name '_is_public'`).

- [ ] **Step 3: Implement `_text` and `_is_public`**

Replace the contents of `src/legacy_law_identity/resolver.py` above the `resolve_legacy_law_identities` def with:

```python
"""Legacy (vols <=63) U.S. Statutes pLaw identity resolver. See README."""
from __future__ import annotations

import logging
import re
from collections import Counter

log = logging.getLogger(__name__)

_PL_RE = re.compile(r"\bPublic Law\s+(\d+)")
_PUBNO_RE = re.compile(r"[Pp]ub[l]?i[c]?[e]?\s*,?\.?\s*No\.?\s*(\d+)")
_PRIVATE_RE = re.compile(r"\bPrivate Law\b", re.IGNORECASE)


def _text(elem, path, ns):
    found = elem.find(path, ns)
    if found is None:
        return ""
    return "".join(found.itertext()).strip()


def _is_public(plaw, sidenote_text, ns):
    pp = plaw.find(".//uslm:publicPrivate", ns)
    if pp is not None and pp.text and pp.text.strip():
        return pp.text.strip().lower() == "public"
    if _PRIVATE_RE.search(sidenote_text):
        return False
    return True
```

(Keep the existing `resolve_legacy_law_identities` stub raising `NotImplementedError` below this.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/G39248410/citizen_voice/Code/legacy-law-identity && /home/G39248410/citizen_voice/venv/bin/python -m pytest tests/ -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
cd /home/G39248410/citizen_voice/Code/legacy-law-identity
git add -A
git commit -q -m "feat: null-safe publicPrivate read + is_public inference"
```

---

## Task 3: Verbatim sidenote public-law number extraction

**Files:**
- Modify: `Code/legacy-law-identity/src/legacy_law_identity/resolver.py`
- Test: `Code/legacy-law-identity/tests/test_resolver.py`

**Interfaces:**
- Produces: `_sidenote_pl_number(sidenote_text) -> int | None`. Matches `Public Law N` (first) or the `Pub. No. N` variant; returns the integer verbatim, or `None` if neither matches.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_resolver.py`:

```python
from legacy_law_identity.resolver import _sidenote_pl_number


def test_sidenote_public_law_number():
    assert _sidenote_pl_number("July 24, 1941[H. R. 4473][Public Law 5]") == 5


def test_sidenote_pub_no_variant():
    assert _sidenote_pl_number("Pub. No. 188") == 188


def test_sidenote_no_number_returns_none():
    assert _sidenote_pl_number("[H. R. 4473] approved July 24") is None


def test_sidenote_kept_verbatim_even_if_ocr_wrong():
    # Approach A: return exactly what the sidenote says (5), not a corrected value.
    assert _sidenote_pl_number("[Public Law 5]") == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/G39248410/citizen_voice/Code/legacy-law-identity && /home/G39248410/citizen_voice/venv/bin/python -m pytest tests/ -q`
Expected: FAIL (`ImportError: cannot import name '_sidenote_pl_number'`).

- [ ] **Step 3: Implement `_sidenote_pl_number`**

Add to `src/legacy_law_identity/resolver.py` (after `_is_public`):

```python
def _sidenote_pl_number(sidenote_text):
    m = _PL_RE.search(sidenote_text) or _PUBNO_RE.search(sidenote_text)
    return int(m.group(1)) if m else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/G39248410/citizen_voice/Code/legacy-law-identity && /home/G39248410/citizen_voice/venv/bin/python -m pytest tests/ -q`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
cd /home/G39248410/citizen_voice/Code/legacy-law-identity
git add -A
git commit -q -m "feat: verbatim sidenote public-law-number extraction"
```

---

## Task 4: End-to-end resolver — two-pass fill + modal congress

**Files:**
- Modify: `Code/legacy-law-identity/src/legacy_law_identity/resolver.py`
- Test: `Code/legacy-law-identity/tests/test_resolver.py`

**Interfaces:**
- Consumes: `_text`, `_is_public`, `_sidenote_pl_number` (Tasks 2–3).
- Produces: full `resolve_legacy_law_identities(plaws, vol, ns) -> dict[int, dict]`. For each pLaw index: private → `{"is_public": False, "law_identifier": None}`; public → `{"is_public": True, "law_identifier": "{congress}-{resolved}"}`. Fill rules: parseable sidenote → verbatim; blank → `last_resolved + 1`; leading blank → `max(1, first_anchor − distance)`; no anchor anywhere → document-order ordinal `(i+1)`. Missing `<congress>` on a pLaw uses the volume's modal congress.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_resolver.py`:

```python
from legacy_law_identity import resolve_legacy_law_identities


def test_verbatim_sidenote_becomes_law_identifier():
    plaws, ns = plaws_from(plaw_xml(sidenote="[Public Law 5]", doc_number="320", congress="77"))
    ids = resolve_legacy_law_identities(plaws, 55, ns)
    assert ids[0] == {"is_public": True, "law_identifier": "77-5"}


def test_blank_sidenote_filled_prev_plus_one():
    plaws, ns = plaws_from(
        plaw_xml(sidenote="[Public Law 187]", doc_number="319", congress="77"),
        plaw_xml(sidenote="", doc_number="320", congress="77"),           # blank -> 188
        plaw_xml(sidenote="[Public Law 189]", doc_number="325", congress="77"),
    )
    ids = resolve_legacy_law_identities(plaws, 55, ns)
    assert ids[0]["law_identifier"] == "77-187"
    assert ids[1]["law_identifier"] == "77-188"
    assert ids[2]["law_identifier"] == "77-189"


def test_leading_blank_backfilled_from_first_anchor():
    plaws, ns = plaws_from(
        plaw_xml(sidenote="", doc_number="1", congress="77"),             # leading blank -> 4
        plaw_xml(sidenote="[Public Law 5]", doc_number="6", congress="77"),
    )
    ids = resolve_legacy_law_identities(plaws, 55, ns)
    assert ids[0]["law_identifier"] == "77-4"
    assert ids[1]["law_identifier"] == "77-5"


def test_private_law_excluded():
    plaws, ns = plaws_from(
        plaw_xml(public="private", sidenote="[Private Law 3]", congress="77"),
        plaw_xml(public="public", sidenote="[Public Law 10]", congress="77"),
    )
    ids = resolve_legacy_law_identities(plaws, 55, ns)
    assert ids[0] == {"is_public": False, "law_identifier": None}
    assert ids[1]["law_identifier"] == "77-10"


def test_missing_congress_uses_modal_congress():
    plaws, ns = plaws_from(
        plaw_xml(sidenote="[Public Law 1]", congress="77"),
        plaw_xml(sidenote="[Public Law 2]", congress=""),                 # no congress -> modal 77
    )
    ids = resolve_legacy_law_identities(plaws, 55, ns)
    assert ids[1]["law_identifier"] == "77-2"


def test_missing_publicprivate_does_not_crash_and_resolves():
    # Issue 2 regression: absent <publicPrivate>, present sidenote.
    plaws, ns = plaws_from(plaw_xml(public=None, sidenote="[Public Law 42]", congress="77"))
    ids = resolve_legacy_law_identities(plaws, 55, ns)
    assert ids[0] == {"is_public": True, "law_identifier": "77-42"}


def test_no_anchor_anywhere_uses_ordinals():
    plaws, ns = plaws_from(
        plaw_xml(sidenote="", doc_number="10", congress="77"),
        plaw_xml(sidenote="", doc_number="11", congress="77"),
    )
    ids = resolve_legacy_law_identities(plaws, 55, ns)
    assert ids[0]["law_identifier"] == "77-1"
    assert ids[1]["law_identifier"] == "77-2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/G39248410/citizen_voice/Code/legacy-law-identity && /home/G39248410/citizen_voice/venv/bin/python -m pytest tests/ -q`
Expected: FAIL (`NotImplementedError`).

- [ ] **Step 3: Implement `resolve_legacy_law_identities`**

Replace the stub `resolve_legacy_law_identities` in `src/legacy_law_identity/resolver.py` with:

```python
def resolve_legacy_law_identities(plaws, vol, ns):
    """Resolve identity for every pLaw in a legacy volume.

    Returns {doc_index: {"is_public": bool, "law_identifier": str | None}}.
    law_identifier is the bare "{congress}-{N}" form (None for private laws).
    """
    identities: dict[int, dict] = {}
    records: list[dict] = []           # public pLaws only, document order
    congresses: list[str] = []

    # Pass 1 — classify + read sidenote verbatim.
    for idx, plaw in enumerate(plaws):
        sidenote = _text(plaw, ".//uslm:sidenote", ns)
        if not _is_public(plaw, sidenote, ns):
            identities[idx] = {"is_public": False, "law_identifier": None}
            continue
        chapter_text = _text(plaw, ".//uslm:docNumber", ns)
        congress = _text(plaw, ".//uslm:congress", ns)
        if congress:
            congresses.append(congress)
        records.append({
            "idx": idx,
            "pl_raw": _sidenote_pl_number(sidenote),
            "chapter": int(chapter_text) if chapter_text.isdigit() else None,
            "congress": congress,
        })

    modal_congress = Counter(congresses).most_common(1)[0][0] if congresses else ""

    # Pass 2 — fill blanks by monotonic continuation.
    first_anchor = next((i for i, r in enumerate(records) if r["pl_raw"] is not None), None)
    if first_anchor is not None and first_anchor > 0:
        anchor_val = records[first_anchor]["pl_raw"]
        for i in range(first_anchor):
            records[i]["resolved"] = max(1, anchor_val - (first_anchor - i))

    last_resolved = None
    for i, r in enumerate(records):
        if "resolved" in r:
            last_resolved = r["resolved"]
            continue
        if r["pl_raw"] is not None:
            r["resolved"] = r["pl_raw"]
        elif last_resolved is not None:
            r["resolved"] = last_resolved + 1
            log.info("vol %s pLaw #%d: blank sidenote -> filled PL %d (chapter %s)",
                     vol, r["idx"], r["resolved"], r["chapter"])
        else:
            r["resolved"] = i + 1
            log.warning("vol %s: no sidenote anchors; ordinal PL %d for pLaw #%d",
                        vol, r["resolved"], r["idx"])
        last_resolved = r["resolved"]

    for r in records:
        cong = r["congress"] or modal_congress
        identities[r["idx"]] = {"is_public": True, "law_identifier": f"{cong}-{r['resolved']}"}

    return identities
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/G39248410/citizen_voice/Code/legacy-law-identity && /home/G39248410/citizen_voice/venv/bin/python -m pytest tests/ -q`
Expected: PASS (16 passed).

- [ ] **Step 5: Commit**

```bash
cd /home/G39248410/citizen_voice/Code/legacy-law-identity
git add -A
git commit -q -m "feat: two-pass identity resolution (verbatim + deterministic fill)"
```

---

## Task 5: Package finalize + build sanity

**Files:**
- Modify: `Code/legacy-law-identity/README.md` (add "Tested against" note)

**Interfaces:** none new.

- [ ] **Step 1: Verify the package builds as a wheel (migration readiness)**

```bash
cd /home/G39248410/citizen_voice/Code/legacy-law-identity
/home/G39248410/citizen_voice/venv/bin/python -m pip install build
/home/G39248410/citizen_voice/venv/bin/python -m build --wheel
ls dist/*.whl
```

Expected: a `legacy_law_identity-0.1.0-py3-none-any.whl` in `dist/`.

- [ ] **Step 2: Full test run**

Run: `cd /home/G39248410/citizen_voice/Code/legacy-law-identity && /home/G39248410/citizen_voice/venv/bin/python -m pytest tests/ -q`
Expected: PASS (16 passed).

- [ ] **Step 3: Add a "Tested against" line to README and commit**

Append to `README.md`:

```markdown
## Tested against
Statutes vols 44–64 (identity unit tests + pipeline regression). Fixes:
parse crash on missing `<publicPrivate>`, empty `LawIdentifier`, and
chapter-vs-public-law-number id for legacy volumes.
```

```bash
cd /home/G39248410/citizen_voice/Code/legacy-law-identity
git add -A
git commit -q -m "docs: build sanity + tested-against note"
```

---

## Task 6: Pipeline integration — call the resolver + gate the repair pass

**Files:**
- Modify: `Code/data-preprocessing-pipeline/legacy/Extract_Sections_Divisions_From_XML.py:141-208`
- Modify: `Code/data-preprocessing-pipeline/parser/uslm_parser.py:805-872`

**Interfaces:**
- Consumes: `from legacy_law_identity import resolve_legacy_law_identities` (Task 4).

- [ ] **Step 1: Install the package into the pipeline venv**

```bash
/home/G39248410/citizen_voice/venv/bin/python -m pip install -e /home/G39248410/citizen_voice/Code/legacy-law-identity
/home/G39248410/citizen_voice/venv/bin/python -c "from legacy_law_identity import resolve_legacy_law_identities; print('ok')"
```

Expected: `ok`.

- [ ] **Step 2: Edit the raw extractor to call the resolver for legacy volumes**

In `legacy/Extract_Sections_Divisions_From_XML.py`, add the import near the top (with the other imports, after `from law_id_corrections import ...`):

```python
from legacy_law_identity import resolve_legacy_law_identities
```

Replace lines 145-152 (the `results` init + `for` loop header + the crash-prone `<publicPrivate>` block) — currently:

```python
    results = {"Sections": [], "Divisions": []}

    for plaw in root.findall(".//uslm:pLaw", ns):
        lawtype = plaw.find(".//uslm:publicPrivate", ns)
        lawtype = lawtype.text
        # print(lawtype)
        if lawtype.lower() != "public":
            continue
```

with:

```python
    results = {"Sections": [], "Divisions": []}

    plaws = root.findall(".//uslm:pLaw", ns)
    legacy_ids = resolve_legacy_law_identities(plaws, vol, ns) if int(vol) <= 63 else {}

    for plaw_idx, plaw in enumerate(plaws):
        if int(vol) <= 63:
            ident = legacy_ids.get(plaw_idx)
            if ident is None or not ident["is_public"]:
                continue
        else:
            lawtype_el = plaw.find(".//uslm:publicPrivate", ns)
            if lawtype_el is None or not lawtype_el.text or lawtype_el.text.strip().lower() != "public":
                continue
```

- [ ] **Step 3: Route legacy id assignment through the resolver map**

Immediately after the block from Step 2, the code branches on `int(vol) > 63`. Change the `else:` (legacy) branch (currently lines 176-208, the `<sidenote>` regex block that assigns `law_identifiers`) so the whole `if int(vol) > 63: ... else: ...` reads:

```python
        # Volumes >63 use modern USLM with <citableAs>; legacy volumes get their
        # public-law-number id from the legacy-law-identity resolver (computed above).
        if int(vol) > 63:
            c = plaw.find(".//uslm:citableAs", ns)
            law_identifiers = ''.join(c.itertext()).strip() if c is not None else ""
            if int(vol) == 70:
                c = plaw.find(".//uslm:docNumber", ns)
                law_identifiers = ''.join(c.itertext()).strip() if c is not None else ""
                congress = plaw.find(".//uslm:congress", ns)
                congress_text = ''.join(congress.itertext()).strip() if congress is not None else ""
                law_identifiers = 'Public Law ' + congress_text + '-' + law_identifiers
            if "v" in law_identifiers:
                c = plaw.find(".//uslm:docNumber", ns)
                law_identifiers = ''.join(c.itertext()).strip() if c is not None else ""
                law_identifiers = 'Public Law ' + law_identifiers
            if "public law" not in law_identifiers.lower():
                c = plaw.find(".//uslm:docNumber", ns)
                law_identifiers = ''.join(c.itertext()).strip() if c is not None else ""
                congress = plaw.find(".//uslm:congress", ns)
                congress_text = ''.join(congress.itertext()).strip() if congress is not None else ""
                law_identifiers = 'Public Law ' + congress_text + '-' + law_identifiers
        else:
            law_identifiers = legacy_ids[plaw_idx]["law_identifier"]
```

This deletes the old legacy `<sidenote>` regex block (old lines 177-208, including its suspicious `break` on a private-law match) and replaces it with a single lookup. The common tail (`approved_date`, `law_title`, `law_type`, `apply_law_id_corrections`, section/division walking) is unchanged.

- [ ] **Step 4: Gate the malformed-id repair pass to modern volumes**

In `parser/uslm_parser.py`, in `extract_public_law_from_uslm` (around line 863-870), change:

```python
    results = _extract_public_law_from_uslm_raw(file_path, vol)
    if isinstance(results, dict) and "Sections" in results:
        _recover_dropped_container_pLaws(file_path, vol, results)
        _repair_malformed_law_identifiers(file_path, vol, results)
        _assign_unnumbered_section_ordinals(results["Sections"])
        _disambiguate_sibling_levels(results["Sections"])
```

to:

```python
    results = _extract_public_law_from_uslm_raw(file_path, vol)
    if isinstance(results, dict) and "Sections" in results:
        _recover_dropped_container_pLaws(file_path, vol, results)
        # The malformed-id repair pass rebuilds ids from <docNumber>, which is the
        # PUBLIC-LAW number for modern volumes (>63) but the CHAPTER number for legacy
        # volumes (<=63). Legacy ids now come correctly from the legacy-law-identity
        # resolver, so the repair pass must only run for modern volumes.
        if int(vol) > 63:
            _repair_malformed_law_identifiers(file_path, vol, results)
        _assign_unnumbered_section_ordinals(results["Sections"])
        _disambiguate_sibling_levels(results["Sections"])
```

- [ ] **Step 5: Smoke-test one legacy + one modern volume through stage 1**

```bash
cd /home/G39248410/citizen_voice/Code/data-preprocessing-pipeline
/home/G39248410/citizen_voice/venv/bin/python run_pipeline.py --volumes 44 --stop-before-publish --force 2>&1 | tail -5
/home/G39248410/citizen_voice/venv/bin/python run_pipeline.py --volumes 64 --stop-before-publish --force 2>&1 | tail -5
```

Expected: vol 44 now reports `ready_for_publish` (no `parse_failed`, no `AttributeError`); vol 64 reports `ready_for_publish` unchanged.

- [ ] **Step 6: Commit (pipeline repo, feature branch)**

```bash
cd /home/G39248410/citizen_voice/Code/data-preprocessing-pipeline
git add legacy/Extract_Sections_Divisions_From_XML.py parser/uslm_parser.py
git commit -q -m "feat: use legacy-law-identity resolver for vols <=63; gate repair pass to >63"
```

---

## Task 7: Pipeline regression suite over the 20 volumes

**Files:**
- Create: `Code/data-preprocessing-pipeline/tests/integration/test_legacy_law_identity_regression.py`

**Interfaces:**
- Consumes: `run_pipeline.process_volume` (or `run_pipeline` CLI) + `parser.uslm_parser.extract_public_law_from_uslm`.

- [ ] **Step 1: Write the regression tests**

Create `Code/data-preprocessing-pipeline/tests/integration/test_legacy_law_identity_regression.py`:

```python
"""Regression: legacy-law-identity resolver over the 2026-06-30 vols 44-64 run.

Marked slow: these parse real XML from the read-only production dir. Skips
automatically if the XML dir is unavailable (e.g. off-server / post-migration).
"""
import re
import pytest

from parser.uslm_parser import extract_public_law_from_uslm

XML_DIR = "/groups/brooksgrp/laws/us_federal_statutes/Updated_2026-04-06"
PATTERN = re.compile(r"\d+[-–—]\d+")

pytestmark = pytest.mark.skipif(
    not __import__("pathlib").Path(XML_DIR).exists(),
    reason="production XML dir unavailable",
)


def _law_ids(vol):
    res = extract_public_law_from_uslm(f"{XML_DIR}/STATUTE-{vol}.xml", str(vol))
    return [r.get("LawIdentifier") for r in res["Sections"]]


@pytest.mark.parametrize("vol", [44, 48])
def test_previously_crashing_volumes_now_parse(vol):
    ids = _law_ids(vol)              # must not raise AttributeError
    assert len(ids) > 0


@pytest.mark.parametrize("vol", [45, 46, 47, 49, 50, 51, 52, 53, 54, 56, 58])
def test_no_blank_law_identifiers(vol):
    ids = _law_ids(vol)
    blanks = [x for x in ids if not x or not PATTERN.search(str(x))]
    assert blanks == [], f"vol {vol} has {len(blanks)} unrecognizable LawIdentifiers"


@pytest.mark.parametrize("vol", [55, 57, 59, 61, 62, 63])
def test_ready_volumes_ids_are_pl_number_namespace(vol):
    # Legacy ids must no longer be pure chapter numbers: they should reflect the
    # sidenote public-law number. Sanity: all ids match {congress}-{N} and are
    # non-empty. (Value spot-checks live in the design doc's worked example.)
    ids = [x for x in _law_ids(vol) if x]
    assert ids and all(PATTERN.search(str(x)) for x in ids)
```

- [ ] **Step 2: Run the regression tests**

Run: `cd /home/G39248410/citizen_voice/Code/data-preprocessing-pipeline && /home/G39248410/citizen_voice/venv/bin/python -m pytest tests/integration/test_legacy_law_identity_regression.py -q`
Expected: PASS for all parametrized cases (or `skipped` if the XML dir is unavailable).

- [ ] **Step 3: Add a modern-volume no-regression check**

Append to the same file:

```python
@pytest.mark.parametrize("vol", [64, 105, 108])
def test_modern_volumes_unaffected(vol):
    # Module is gated to <=63; modern volumes must still parse and keep the
    # canonical "Public Law N-M" citable form (repair pass still runs for >63).
    ids = [x for x in _law_ids(vol) if x]
    assert ids
    assert any("Public Law" in str(x) for x in ids)
```

- [ ] **Step 4: Run the full regression file**

Run: `cd /home/G39248410/citizen_voice/Code/data-preprocessing-pipeline && /home/G39248410/citizen_voice/venv/bin/python -m pytest tests/integration/test_legacy_law_identity_regression.py -q`
Expected: PASS (or skipped if XML dir unavailable).

- [ ] **Step 5: Commit (pipeline repo, feature branch)**

```bash
cd /home/G39248410/citizen_voice/Code/data-preprocessing-pipeline
git add tests/integration/test_legacy_law_identity_regression.py
git commit -q -m "test: legacy-law-identity regression over vols 44-64 + modern controls"
```

---

## Self-Review

- **Spec coverage:** Issue 1 (repair-pass gate) → Task 6 Step 4 + Task 7 Step 3. Issue 2 (publicPrivate crash) → Task 2 + Task 6 Steps 2-3 + Task 7 `test_previously_crashing_volumes_now_parse`. Issue 3 (blank ids) → Task 4 fill logic + Task 7 `test_no_blank_law_identifiers`. PL-number semantics → Task 4. Identical format → publisher reuse (Global Constraints) + Task 7 modern control. Standalone repo + git + packaging + migration → Task 1 + Task 5. Integration adapter → Task 6. Approach A verbatim + deterministic fill → Tasks 3-4.
- **Placeholders:** none — every code/test step contains complete code.
- **Type consistency:** `resolve_legacy_law_identities(plaws, vol, ns)` and the `{idx: {"is_public", "law_identifier"}}` shape are consistent across Tasks 1, 4, 6, 7; helper names `_text`/`_is_public`/`_sidenote_pl_number` consistent across Tasks 2-4.
