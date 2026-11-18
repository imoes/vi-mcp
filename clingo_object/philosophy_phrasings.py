"""More phrasings per fact type for a philosophy's training rows (0.70.1) — package data with provenance, kept OUT of the package.

Why: reading sentences in phrasings never seen in training was the bottleneck of the fine-tuning runs (FINETUNING_PAPER §5.9–5.11):
with the package's 2–3 phrasings per fact type, held-out phrasings were read right in 3–7 of 40 worlds; with 150–330 filtered
phrasings per type from several generator families, 37–40 of 40. The pool lives next to the package (philosophy_<name>_phrasings.py)
and never inside it: the package's hash — and every binding to it — stays the same, and the held-out phrasings (render_test) stay
the package's own.

Every phrasing in a pool was written by a generator and read back by a model of another family: two random fillings of the template
had to come back as exactly the fact (filter_para2.py for the eight 1.2.0 types, filter_para13.py for the eight 1.3.0 types). `pool`
checks again what can be checked without a model: the placeholders are those of the package's own templates, and no phrasing is close
to a held-out one (word Jaccard < 0.5)."""
from __future__ import annotations

import importlib
import re

JACCARD_MAX = 0.5


def _toks(s: str) -> set[str]:
    return set(re.findall(r"[a-z]+", s.lower())) - {"s", "w"}


def _phs(t: str) -> list[str]:
    return sorted(re.findall(r"\{(w?\d)\}", t))


def load_data(pkg: dict) -> dict | None:
    """The pool module clingo_object/philosophy_<name>_phrasings.py (DATA), or None. A module, not a data file: package builds and
    kits bundle clingo_object/*.py only."""
    if not re.fullmatch(r"[a-z0-9_]+", str(pkg.get("name", ""))):
        return None
    try:
        return importlib.import_module(f"{__package__}.philosophy_{pkg['name']}_phrasings").DATA
    except ModuleNotFoundError:
        return None


def pool(pkg: dict) -> dict[str, list[str]]:
    """The extra training phrasings for this package ({type: [templates]}); {} when there is no pool for its name and major.minor.
    A template that no longer fits the package (placeholders) or comes close to a held-out phrasing is left out, never used."""
    data = load_data(pkg)
    if data is None:
        return {}
    if not str(pkg.get("version", "")).startswith(str(data.get("versions", "")).rstrip("x")):
        return {}
    out = {}
    for t, items in (data.get("phrasings") or {}).items():
        if t not in pkg.get("render", {}):
            continue
        want = _phs(pkg["render"][t][0])
        tests = [_toks(x) for x in pkg.get("render_test", {}).get(t, [])]
        out[t] = [x for x in items if _phs(x) == want and x not in pkg["render"][t]
                  and all(len(_toks(x) & y) / max(1, len(_toks(x) | y)) < JACCARD_MAX for y in tests)]
    return out


def training_table(pkg: dict) -> dict[str, list[str]]:
    """The package's own training phrasings plus the pool — what training rows are rendered from (never the held-out ones)."""
    extra = pool(pkg)
    return {t: list(v) + extra.get(t, []) for t, v in pkg["render"].items()}
