"""Measure the search against a question set with known targets (0.55.0, vi_mcp/evaluation.py).

    python scripts/eval_recall.py --db COPY.db --questions recall.json [--variant fulltext --variant hybrid] [--embed-url URL] [--out result.json]

Run it against a COPY of the database: opening a database migrates its schema. The question file holds internal content and stays
outside the repository. Without --embed-url the hybrid variant is skipped (it needs the embedding service for the query).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vi_mcp import evaluation, memory as g, vector  # noqa: E402


def main() -> int:
    a = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    a.add_argument("--db", required=True)
    a.add_argument("--questions", required=True)
    a.add_argument("--variant", action="append", choices=sorted(evaluation.VARIANTS), default=None)
    a.add_argument("--embed-url", default=None, help="OpenAI-compatible /v1/embeddings URL for the query vector (hybrid)")
    a.add_argument("--out", default=None, help="write summary and rows as JSON")
    o = a.parse_args()
    if o.embed_url:
        vector.config = {"url": o.embed_url}
    g.open_db(o.db)
    questions = evaluation.load_questions(o.questions)
    results = {}
    for name in o.variant or sorted(evaluation.VARIANTS):
        if name == "hybrid" and not vector.available():
            print("hybrid skipped: no --embed-url", file=sys.stderr)
            continue
        results[name] = evaluation.run(questions, evaluation.VARIANTS[name])
        print(f"{name}: {results[name]['gesamt']}", file=sys.stderr)
    print(evaluation.table(results))
    if o.out:
        Path(o.out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
