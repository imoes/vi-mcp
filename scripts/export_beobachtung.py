"""Export vi-mcp-Erfahrungen → Trainingsmatrix. Nur sqlite3/json/numpy/scipy (kein sklearn).
X = CSR (n_erfahrungen × n_merkmale, 0/1), y = ok (1/0); ok:unbekannt wird ausgelassen (kein Label)."""
import json, sqlite3, sys
import numpy as np, scipy.sparse as sp

def load_observations(db_path):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    sql = """SELECT o.id, o.zeit, o.daten, group_concat(t.tag, ' ') FROM objekt o JOIN tag t ON t.objekt_id = o.id
             WHERE o.art = 'erfahrung' GROUP BY o.id"""
    for oid, ts, data, tags in con.execute(sql):
        tags, d = set(tags.split()), json.loads(data)
        ok = "ok:ja" in tags
        if "ok:unbekannt" in tags: continue                       # kein Label → kein Beispiel
        before = d.get("vorher") or {}
        features = {t for t in tags if t.startswith(("tool:", "skill:", "host:"))}
        features |= {t for t in before.get("reize", []) if t.startswith("thema:")}   # nur im JSON, nicht in tag
        features |= {f"hinweis:{h.split(':')[0]}" for h in before.get("gefunden", []) if not h.startswith("antwort:")}
        features.add(f"hinweis_n:{min(4, sum(1 for h in before.get('gefunden', []) if not h.startswith('antwort:')))}")
        features.add(f"stunde:{ts[11:13]}")                        # Tageszeit (UTC) aus ISO-Zeit
        yield oid, sorted(features), int(ok)

def dict_vector(obs):
    """Minimal-DictVectorizer: Merkmalsname → Spalte; Ergebnis CSR 0/1 (entspricht sklearn DictVectorizer(sparse=True))."""
    column, lines, columns, y, ids = {}, [], [], [], []
    for i, (oid, features, ok) in enumerate(obs):
        for m in features:
            lines.append(i); columns.append(column.setdefault(m, len(column)))
        y.append(ok); ids.append(oid)
    X = sp.csr_matrix((np.ones(len(lines), dtype=np.float32), (lines, columns)), shape=(len(y), len(column)))
    return X, np.array(y, dtype=np.int8), np.array(sorted(column, key=column.get)), np.array(ids)

if __name__ == "__main__":
    X, y, names, ids = dict_vector(list(load_observations(sys.argv[1])))
    sp.save_npz(sys.argv[2] + ".X.npz", X); np.savez(sys.argv[2] + ".meta.npz", y=y, features=names, ids=ids)
    print(f"X {X.shape} nnz={X.nnz}  y: {y.sum()} ok von {len(y)}\nMerkmale: {list(names)}")
    print("Zeile 0:", [names[j] for j in X[0].indices], "→ y =", y[0])
