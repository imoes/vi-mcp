"""Export vi-mcp-Erfahrungen → Trainingsmatrix. Nur sqlite3/json/numpy/scipy (kein sklearn).
X = CSR (n_erfahrungen × n_merkmale, 0/1), y = ok (1/0); ok:unbekannt wird ausgelassen (kein Label)."""
import json, sqlite3, sys
import numpy as np, scipy.sparse as sp

def lade_beobachtungen(db_pfad):
    con = sqlite3.connect(f"file:{db_pfad}?mode=ro", uri=True)
    sql = """SELECT o.id, o.zeit, o.daten, group_concat(t.tag, ' ') FROM objekt o JOIN tag t ON t.objekt_id = o.id
             WHERE o.art = 'erfahrung' GROUP BY o.id"""
    for oid, zeit, daten, tags in con.execute(sql):
        tags, d = set(tags.split()), json.loads(daten)
        ok = "ok:ja" in tags
        if "ok:unbekannt" in tags: continue                       # kein Label → kein Beispiel
        vorher = d.get("vorher") or {}
        merkmale = {t for t in tags if t.startswith(("tool:", "skill:", "host:"))}
        merkmale |= {t for t in vorher.get("reize", []) if t.startswith("thema:")}   # nur im JSON, nicht in tag
        merkmale |= {f"hinweis:{h.split(':')[0]}" for h in vorher.get("gefunden", []) if not h.startswith("antwort:")}
        merkmale.add(f"hinweis_n:{min(4, sum(1 for h in vorher.get('gefunden', []) if not h.startswith('antwort:')))}")
        merkmale.add(f"stunde:{zeit[11:13]}")                        # Tageszeit (UTC) aus ISO-Zeit
        yield oid, sorted(merkmale), int(ok)

def dict_vektor(beob):
    """Minimal-DictVectorizer: Merkmalsname → Spalte; Ergebnis CSR 0/1 (entspricht sklearn DictVectorizer(sparse=True))."""
    spalte, zeilen, spalten, y, ids = {}, [], [], [], []
    for i, (oid, merkmale, ok) in enumerate(beob):
        for m in merkmale:
            zeilen.append(i); spalten.append(spalte.setdefault(m, len(spalte)))
        y.append(ok); ids.append(oid)
    X = sp.csr_matrix((np.ones(len(zeilen), dtype=np.float32), (zeilen, spalten)), shape=(len(y), len(spalte)))
    return X, np.array(y, dtype=np.int8), np.array(sorted(spalte, key=spalte.get)), np.array(ids)

if __name__ == "__main__":
    X, y, namen, ids = dict_vektor(list(lade_beobachtungen(sys.argv[1])))
    sp.save_npz(sys.argv[2] + ".X.npz", X); np.savez(sys.argv[2] + ".meta.npz", y=y, merkmale=namen, ids=ids)
    print(f"X {X.shape} nnz={X.nnz}  y: {y.sum()} ok von {len(y)}\nMerkmale: {list(namen)}")
    print("Zeile 0:", [namen[j] for j in X[0].indices], "→ y =", y[0])
