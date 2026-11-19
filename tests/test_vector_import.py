"""0.70.4: vectors of an external index computed elsewhere — export of the texts, a checked all-or-nothing import."""
import json

import numpy as np
import pytest

from vi_mcp import indexes, vector, vector_import
from vi_mcp import memory as g


def _fake_embed(texts, timeout=None):
    """deterministic stand-in for the embedding service: a vector from the text's hash"""
    out = []
    for t in texts:
        r = np.random.default_rng(abs(hash(t)) % (2 ** 32)).standard_normal(8).astype(np.float32)
        out.append((r / np.linalg.norm(r)).tolist())
    return out


@pytest.fixture
def corpus(gd, monkeypatch, tmp_path):
    monkeypatch.setattr(vector, "embed_texts", _fake_embed)
    pages = [g.new_object("insight", f"corpus page number {i} about rsync", ["topic:rsync"], {"source": "t"}, instance="importer",
                          index="se-ext") for i in range(12)]
    other = g.new_object("insight", "a normal insight elsewhere", ["topic:rsync"], {"source": "t"}, instance="a")
    indexes.describe("se-ext", scope="external")
    return pages, other, tmp_path


def _write(tmp, ids, m):
    (tmp / "ids.txt").write_text("\n".join(ids) + "\n")
    np.save(tmp / "v.npy", np.asarray(m, dtype=np.float32))
    return tmp / "ids.txt", tmp / "v.npy"


def test_export_writes_the_texts_and_reference_vectors(corpus):
    pages, other, tmp = corpus
    r = vector_import.export("se-ext", tmp / "out", reference=5)
    rows = [json.loads(x) for x in open(tmp / "out" / "texts.jsonl")]
    assert r["texts"] == 12 and {x["id"] for x in rows} == {p.id for p in pages} and other.id not in {x["id"] for x in rows}
    assert np.load(tmp / "out" / "reference.npy").shape == (5, 8)


def test_import_stores_checked_vectors_without_proximity(corpus):
    pages, _other, tmp = corpus
    ids = [p.id for p in pages]
    f_ids, f_v = _write(tmp, ids, _fake_embed([p.text for p in pages]))
    r = vector_import.import_("se-ext", f_ids, f_v, check=5)
    assert r["stored"] == 12 and r["check"]["min_cos"] >= vector_import.CHECK_MIN_COS
    assert vector.load(pages[0].id) is not None
    with g.lock:
        assert g.db().execute("SELECT MIN(compared) FROM vector WHERE id IN ({})".format(",".join("?" * 12)), ids).fetchone()[0] == 1


def test_a_different_model_is_refused_and_nothing_is_stored(corpus):
    pages, _other, tmp = corpus
    wrong = np.random.default_rng(1).standard_normal((12, 8))  # vectors of "another model"
    f_ids, f_v = _write(tmp, [p.id for p in pages], wrong)
    r = vector_import.import_("se-ext", f_ids, f_v, check=5)
    assert "refused" in r and r.get("stored") is None
    assert all(vector.load(p.id) is None for p in pages)


def test_ids_outside_the_index_are_counted_not_stored(corpus):
    pages, other, tmp = corpus
    ids = [p.id for p in pages] + [other.id]
    f_ids, f_v = _write(tmp, ids, _fake_embed([p.text for p in pages] + [other.text]))
    r = vector_import.import_("se-ext", f_ids, f_v, check=3)
    assert r["stored"] == 12 and r["not_in_index"] == 1 and other.id in r["not_in_index_examples"]
    assert vector.load(other.id) is None


def test_fixed_rules_refuse_before_writing(corpus):
    pages, _other, tmp = corpus
    ids = [p.id for p in pages]
    f_ids, f_v = _write(tmp, ids[:5], np.zeros((5, 8)))
    with pytest.raises(ValueError):  # zero vectors
        vector_import.import_("se-ext", f_ids, f_v, check=0)
    f_ids, f_v = _write(tmp, ids, np.ones((11, 8)))
    with pytest.raises(ValueError):  # one row short
        vector_import.import_("se-ext", f_ids, f_v, check=0)
    indexes.describe("se-ext", scope="all")
    f_ids, f_v = _write(tmp, ids, np.ones((12, 8)))
    with pytest.raises(ValueError):  # a normal index is embedded by sleep itself
        vector_import.import_("se-ext", f_ids, f_v, check=0)
