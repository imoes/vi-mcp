# Forschung: Wie wird eine KI trainiert — und wie legen wir vi-mcp-Daten dafür ab?

Stand 2026-11-08. Quellen inline; **[V]** = Primärquelle heute abgerufen (URL bzw. Datei:Zeile), **Hypothese** = nicht belegt.
Geprüft wurde gegen `dem Repository` (Stand 13:22 Uhr; `docs/ARCHITEKTUR.md`, `vi_mcp/gedaechtnis.py`,
`vi_mcp/messung.py`, `vi_mcp/intuition.py`) — nichts verändert. Export-Code wurde gegen eine Wegwerf-Datenbank im
Scratchpad getestet (Abschnitt 4a).

---

## 1. scikit-learn: Datenformat

### 1.1 Das kanonische Eingabeformat: X (2-D) und y (1-D)

scikit-learn hat **keine Datenbank, kein eigenes Dateiformat**. Jeder Estimator nimmt zwei Arrays entgegen:

> „The samples matrix (or design matrix) X. The size of `X` is typically `(n_samples, n_features)`, which means that
> samples are represented as rows and features are represented as columns.“
> „`y` is usually a 1d array where the `i` th entry corresponds to the target of the `i` th sample (row) of `X`.“
> „Both `X` and `y` are usually expected to be numpy arrays or equivalent array-like data types, though some estimators
> work with other formats such as sparse matrices.“
> — https://scikit-learn.org/stable/getting_started.html **[V]**

Begriffe laut Glossar (https://scikit-learn.org/stable/glossary.html **[V]**):

- **array-like**: „any type object for which `numpy.asarray` will produce an array of appropriate shape (usually 1 or
  2-dimensional) of appropriate dtype (usually numeric).“ — also auch Python-Listen und pandas-DataFrames.
- **sparse matrix**: „A representation of two-dimensional numeric data that is more memory efficient than the
  corresponding dense numpy array where almost all elements are zero. We use the `scipy.sparse` framework“.
- **sample** = eine Zeile („a single feature vector“), **feature** = eine Spalte („In a data matrix, features are
  represented as columns“).

Die API ist überall gleich: `fit(X, y)` lernt, `predict(X)` sagt vorher, Transformer haben `transform(X)`; alle erben
von `BaseEstimator` (getting_started **[V]**).

### 1.2 Was sklearn im Code tatsächlich akzeptiert (Repo-Prüfung)

Quelle: https://github.com/scikit-learn/scikit-learn, Branch `main`, Rohdateien heute heruntergeladen **[V]**:

| Datei | Fundstelle | Was dort steht |
|---|---|---|
| `sklearn/utils/validation.py` | `check_array`, Z. 729; Docstring Z. 747 | „Input validation on an array, list, sparse matrix or similar.“ Parameter `array : object` (Z. 755); `accept_sparse` (Z. 758): erlaubte Sparse-Formate (`'csr'`, `'csc'` …), `False` → Fehler bei Sparse-Eingabe |
| ebd. | Z. 881, 887, 930 | pandas wird ausdrücklich behandelt: „For dataframes, use narwhals“, „pandas.DataFrame may have sparse columns“, „array is a pandas series or a pandas array“ |
| ebd. | `check_X_y`, Z. 1180; Z. 1210–1213 | `X : {ndarray, list, sparse matrix}` „Input data.“ — `y : {ndarray, list, sparse matrix}` „Labels.“ (y wird auf 1-D geprüft, außer `multi_output`) |
| `sklearn/datasets/_base.py` | Z. 8, 31, 312–320, 325 | `import csv`; Toy-Datensätze liegen als **CSV** im Paket (`load_csv_data`, z. B. `'wine_data.csv'` Z. 339) und kommen als `Bunch` (dict mit `data`, `target`) zurück |
| `sklearn/datasets/_openml.py` | `fetch_openml` Z. 804; `_load_arff_response` Z. 463 | lädt **ARFF** von openml.org, Parser `"liac-arff"` oder `"pandas"` (Z. 490) |

Die Doku bestätigt das Bild (https://scikit-learn.org/stable/datasets/loading_other_datasets.html **[V]**):

> „scikit-learn works on any numeric data stored as numpy arrays or scipy sparse matrices. Other types that are
> convertible to numeric arrays such as pandas DataFrame are also acceptable.“

Empfohlen zum Laden: `pandas.io` (CSV, Excel, JSON, **SQL**), `scipy.io` (`.mat`, `.arff`), `numpy/routines.io`.
Für dünn besetzte Daten gibt es das Textformat **svmlight/libsvm** (`<label> <feature-id>:<feature-value> …`,
„In this module, scipy sparse CSR matrices are used for `X` and numpy arrays are used for `y`“, ebd. **[V]**).
Loader/Fetcher liefern ein `Bunch` mit `data` (n_samples × n_features) und `target` (Länge n_samples), Generatoren
ein Tupel `(X, y)` (https://scikit-learn.org/stable/datasets.html **[V]**).

**Antwort auf die Frage „hat sklearn ein Datenbankformat?“: Nein.** Es konsumiert Arrays; Persistenz ist Sache von
numpy (`.npz`), pandas (CSV/Parquet/SQL) oder scipy (`save_npz` für Sparse). Das ist für uns gut: SQLite bleibt die
Quelle der Wahrheit, der Export ist eine Sicht.

### 1.3 Von Hashtags zum Vektor: DictVectorizer, FeatureHasher, OneHotEncoder, Text-Vectorizer

Genau unser Fall — eine Menge von Zeichenketten (`tool:x`, `host:y`, `thema:z`) soll eine Zeile einer dünn besetzten
Matrix werden (https://scikit-learn.org/stable/modules/feature_extraction.html **[V]**):

- **`DictVectorizer`** (`sklearn/feature_extraction/_dict_vectorizer.py`, Klasse Z. 17 **[V]**): „Transforms lists of
  feature-value mappings to vectors.“ Strings werden „one-hot (aka one-of-K)“ codiert; `sparse : bool, default=True`
  (Z. 57). Beispiel im Docstring (Z. 82): `D = [{'foo': 1, 'bar': 2}, {'foo': 3, 'baz': 1}]`. Er **merkt sich das
  Vokabular** (`fit`) — also die Zuordnung Hashtag → Spalte; `inverse_transform` existiert.
- **`FeatureHasher`** (`sklearn/feature_extraction/_hash.py`, Klasse Z. 21 **[V]**): „Implements feature hashing, aka
  the hashing trick.“ Spalte = Hash des Namens mod `n_features` (`default=2**20`, Z. 45); **stateless**, kein Vokabular,
  kein `inverse_transform`; Kollisionen möglich, `alternate_sign=True` (Z. 63) mildert sie. Nimmt `dict`, Paare oder
  rohe Strings (`input_type`, Z. 49). Passt, wenn das Hashtag-Vokabular offen und groß ist.
- **`OneHotEncoder`** (https://scikit-learn.org/stable/modules/preprocessing.html **[V]**): „transforms each
  categorical feature with `n_categories` possible values into `n_categories` binary features, with one of them 1,
  and all others 0.“ — für **Spalten** mit einer Kategorie je Zeile (z. B. `tool`), nicht für Mengen.
- **`CountVectorizer` / `TfidfVectorizer`** (feature_extraction **[V]**): „We call vectorization the general process
  of turning a collection of text documents into numerical feature vectors“; Bag of Words = „tokenization, counting
  and normalization“; „tf–idf means term-frequency times inverse document-frequency“, Zeilen L2-normiert. Das ist das
  mathematische Gegenstück zu unserem FTS5-`rank` (BM25) — beides gewichtet seltene Wörter höher.

**Praktischer Unterschied für vi-mcp:** `DictVectorizer` braucht ein gespeichertes Vokabular (ein Objekt, das mit dem
Modell versioniert werden muss); `FeatureHasher` nicht, verliert aber die Rückübersetzung „Spalte 4711 = `host:app0815`“
— das verletzt unseren Grundsatz „zureichender Grund“ (CLAUDE.md Regel 4: jedes gelernte Gewicht muss erklärbar
sein). Empfehlung daher **DictVectorizer** (oder der 15-Zeilen-Nachbau in 4a) mit mitgespeicherter Merkmalsliste.

---

## 2. Pipeline / ColumnTransformer (Tutorial Jake Tae)

Quelle: https://jaketae.github.io/study/sklearn-pipeline/ („Scikit-learn Pipelines with Titanic“, 30.05.2020) **[V]**,
dazu getting_started **[V]** für die Leakage-Aussage (das Tutorial selbst spricht Leakage nicht an).

1. Eine **`Pipeline`** kettet Vorverarbeitungsschritte und ein Modell zu *einem* Estimator: „it's just a way of
   chaining different operations together in a convenient object.“
2. Regel: endet die Kette mit einem Transformer → `fit_transform()` dann `transform()`; endet sie mit einem Modell →
   `fit()` dann `predict()`. „Calling `fit()` will cause all steps prior to the model to undergo `fit_transform()`“.
3. **`ColumnTransformer`** = „the magic glue“: je Spaltengruppe eine eigene Teil-Pipeline — im Tutorial numerisch
   (`age`, `fare`, `family_size`: `KNNImputer` → `RobustScaler`) und kategorial (`sex`, `pclass`, `embarked`, …:
   `SimpleImputer(most_frequent)` → `OneHotEncoder` → `PCA`). Heterogene Spalten werden so **in einem Objekt** zu
   einer Matrix.
4. Hyperparameter aller Stufen werden gemeinsam gesucht (`RandomizedSearchCV`, `n_iter=100`; CV ≈ 0,80, Test ≈ 0,84).
5. Warum das zählt: Skalierer/Imputer werden **nur auf Trainingsdaten gefittet** und dann auf Testdaten angewandt —
   die offizielle Doku nennt das als Zweck: „using a pipeline will also prevent you from data leakage, i.e. disclosing
   some testing data in your training data“ (getting_started **[V]**).

**Übertragen auf vi-mcp:** Unsere „Pipeline“ wäre `Export (SQLite → dicts)` → `DictVectorizer` → `LogisticRegression`;
Tageszeit und `ueberraschung` liefen als eigene Spalten durch einen `ColumnTransformer`. Wichtig ist der Leakage-Punkt:
das Vokabular darf nur aus dem Trainingszeitraum stammen, sonst „kennt“ das Modell Hashtags aus der Zukunft.

---

## 3. PyTorch: Dataset, DataLoader, Trainingsschleife, Embeddings

Quellen: https://docs.pytorch.org/tutorials/beginner/basics/data_tutorial.html **[V]**,
https://docs.pytorch.org/tutorials/beginner/basics/quickstart_tutorial.html **[V]**,
https://docs.pytorch.org/docs/2.15/generated/torch.nn.Embedding.html **[V]** (die `stable`-URL leitet dorthin um).

- „PyTorch provides two data primitives: `torch.utils.data.DataLoader` and `torch.utils.data.Dataset`“; „`Dataset`
  stores the samples and their corresponding labels“, `DataLoader` legt einen Iterator darüber (Minibatches,
  Reshuffle je Epoche „to reduce model overfitting“, `multiprocessing` „to speed up data retrieval“).
- „A custom Dataset class must implement three functions: `__init__`, `__len__`, and `__getitem__`.“ — d. h. eine
  Klasse, die Zeile *i* unserer Export-Matrix als Tensor-Paar `(x_i, y_i)` liefert, ist bereits ein Dataset.
- Training in fünf Zeilen (Quickstart, wörtlich): `pred = model(X)` · `loss = loss_fn(pred, y)` · `loss.backward()` ·
  `optimizer.step()` · `optimizer.zero_grad()`. Erklärung ebd.: „the model makes predictions on the training dataset
  (fed to it in batches), and backpropagates the prediction error to adjust the model's parameters.“ Modell =
  Klasse, die von `nn.Module` erbt.
- **`nn.Embedding`**: „A simple lookup table that stores embeddings of a fixed dictionary and size.“ Parameter
  `num_embeddings` („size of the dictionary of embeddings“) und `embedding_dim` („the size of each embedding vector“);
  Eingabe: `IntTensor or LongTensor … containing the indices`, Ausgabe `(*, H)`. Für uns: jedes Hashtag bekommt eine
  Index-Nummer (das DictVectorizer-Vokabular!) und lernt einen Vektor; Hashtags, die in ähnlichen Erfolgs-/Fehler-
  Kontexten vorkommen, landen nahe beieinander. Das ist die gelernte Variante unserer Kanten „≥ 2 gemeinsame
  Hashtags“ (`gedaechtnis.py:331 verknuepfe_aehnliche`).

**Einordnung:** Für n < einige Tausend Beobachtungen ist PyTorch überdimensioniert; die logistische Regression aus
sklearn ist mathematisch dasselbe wie ein einschichtiges `nn.Linear` + Sigmoid + BCE-Loss, nur ohne Schleife.

---

## 4. Abbildung auf vi-mcp

### 4a. Was heute schon ein Trainingssatz ist — und wo es liegt

Jede Erfahrung (`intuition.erfahrung`, `vi_mcp/intuition.py:188`) ist eine Beobachtung mit Merkmalen und Label:

| Merkmal / Label | Wo es liegt | Beleg |
|---|---|---|
| `tool:`, `skill:`, `host:` | Tabelle `tag` | `intuition.py:190–191` (nur `host:`-Reize werden zu Tags) |
| `ok:ja/nein/unbekannt` (**Label**) | Tabelle `tag` | `intuition.py:190` |
| `ueberraschung:<stufe>`, `fehler:<sig>` | Tabelle `tag` | `intuition.py:194–200` |
| Kontext-Reize `thema:…` | **nur** JSON `daten.vorher.reize` | `intuition.py:191` filtert auf `host:`; `reize()` Z. 47 nimmt Kontext auf |
| gezeigte Hinweise (`gefunden`: IDs, daraus Art via Präfix `erkenntnis:`/`regel:`/`suche:`) | **nur** JSON `daten.vorher.gefunden` | `intuition.py:109`, `messung.py:17–19` |
| Tageszeit | Spalte `zeit` (ISO, UTC) | `gedaechtnis.py:99` |
| „aus Gedächtnis beantwortet“ (muss raus, keine Handlung) | JSON `daten.vorher.aus_gedaechtnis` | `messung.py:29` |

**Gegenprobe (Scratchpad-DB, heute):** 6 Erfahrungen angelegt; `SELECT tag FROM tag WHERE objekt_id = …` lieferte
`art:erfahrung, host:app0815, instanz:claude-code, ok:ja, skill:proxmox, tool:proxmox_get_nodes, ueberraschung:keine`
— `thema:ssh` und die `gefunden`-ID standen nur in `daten`. **Befund:** `objekt`+`tag` reichen *fast*; die beiden
wichtigsten Merkmale für die Router-Frage („welcher Hinweis hat genützt?“) stecken im JSON. Für einen Export ist das
unproblematisch (JSON parsen); für SQL-Auswertungen wäre eine **flache Sicht** bequemer.

**Export (getestet, nur sqlite3/json/numpy/scipy — kein sklearn nötig; Skript
`scripts/export_beobachtung.py`):**

```python
def lade_beobachtungen(db_pfad):
    con = sqlite3.connect(f"file:{db_pfad}?mode=ro", uri=True)          # nur lesen
    sql = """SELECT o.id, o.zeit, o.daten, group_concat(t.tag, ' ') FROM objekt o
             JOIN tag t ON t.objekt_id = o.id WHERE o.art = 'erfahrung' GROUP BY o.id"""
    for oid, zeit, daten, tags in con.execute(sql):
        tags, d = set(tags.split()), json.loads(daten)
        if "ok:unbekannt" in tags: continue                             # kein Label → kein Beispiel
        vorher = d.get("vorher") or {}
        merkmale = {t for t in tags if t.startswith(("tool:", "skill:", "host:"))}
        merkmale |= {t for t in vorher.get("reize", []) if t.startswith("thema:")}
        hinweise = [h for h in vorher.get("gefunden", []) if not h.startswith("antwort:")]
        merkmale |= {f"hinweis:{h.split(':')[0]}" for h in hinweise}  # hinweis:erkenntnis / regel / suche
        merkmale.add(f"hinweis_n:{min(4, len(hinweise))}")
        merkmale.add(f"stunde:{zeit[11:13]}")
        yield oid, sorted(merkmale), int("ok:ja" in tags)

def dict_vektor(beob):                     # = sklearn DictVectorizer(sparse=True) in 7 Zeilen
    spalte, zeilen, spalten, y, ids = {}, [], [], [], []
    for i, (oid, merkmale, ok) in enumerate(beob):
        for m in merkmale:
            zeilen.append(i); spalten.append(spalte.setdefault(m, len(spalte)))
        y.append(ok); ids.append(oid)
    X = sp.csr_matrix((np.ones(len(zeilen), dtype=np.float32), (zeilen, spalten)), shape=(len(y), len(spalte)))
    return X, np.array(y, dtype=np.int8), np.array(sorted(spalte, key=spalte.get)), np.array(ids)
# sp.save_npz("beob.X.npz", X); np.savez("beob.meta.npz", y=y, merkmale=namen, ids=ids)
```

Messung heute: `X (6, 8) nnz=39, y: 4 ok von 6`, Merkmale `['hinweis_n:0','host:app0815','skill:proxmox','stunde:12',
'thema:ssh','tool:proxmox_get_nodes','hinweis:erkenntnis','hinweis_n:1']`; `.npz` wieder geladen, Form identisch.
Dieselbe Liste von dicts geht unverändert in `sklearn.feature_extraction.DictVectorizer`; `.npz` lädt `scipy.sparse.
load_npz`, CSV/Parquet via pandas (loading_other_datasets **[V]**).

**Minimale Schema-Ergänzung — Vorschlag, nicht umgesetzt:** keine neue Tabelle, sondern eine **SQL-View** (Identität:
eine Quelle der Wahrheit, CLAUDE.md Regel 1; eine Kopie in `beobachtung(…)` könnte auseinanderlaufen):

```sql
CREATE VIEW beobachtung AS
SELECT o.id AS erfahrung_id, o.zeit, o.instanz,
       (SELECT substr(tag,6) FROM tag WHERE objekt_id=o.id AND tag LIKE 'tool:%')  AS tool,
       CASE WHEN EXISTS(SELECT 1 FROM tag WHERE objekt_id=o.id AND tag='ok:ja') THEN 1
            WHEN EXISTS(SELECT 1 FROM tag WHERE objekt_id=o.id AND tag='ok:nein') THEN 0 END AS ok,   -- NULL = unbekannt, benannt
       json_array_length(o.daten, '$.vorher.gefunden') AS hinweise_n,
       json_extract(o.daten, '$.ueberraschung.stufe')  AS ueberraschung,
       json_extract(o.daten, '$.vorher.reize')         AS reize_json,
       json_extract(o.daten, '$.vorher.gefunden')      AS gefunden_json,
       json_extract(o.daten, '$.vorher.aus_gedaechtnis') AS aus_gedaechtnis
FROM objekt o WHERE o.art = 'erfahrung';
```

(SQLite-JSON1 `json_extract`/`json_array_length` sind in Python 3.12s sqlite3 enthalten — **Hypothese**, heute nicht
gesondert geprüft; der getestete Export braucht sie nicht.) Eine echte Tabelle lohnt erst, wenn die View zu langsam
wird; dann `beobachtung` als Schreib-Nebenprodukt in `intuition.erfahrung`, nicht als Nachlauf.

**Zwei Labels, zwei Fragen:**
- `y1 = ok` — „Gelingt die Handlung?“ (Merkmale: tool, host, thema, stunde, hinweis_n).
- `y2 = ok | hinweis gezeigt` — „Hat *dieser* Hinweis genützt?“ Das ist die Router-Frage; Einheit ist dann das
  **Paar (Erfahrung, gezeigtes Objekt)**, Merkmale = Reize der Handlung × Hashtags des Hinweises. Genau das misst
  `messung.hinweis_lift` heute **aggregiert** (`messung.py:22–37`: Quote mit vs. ohne Hinweis, ab 10 je Seite); ein
  Modell würde dieselbe Zahl **je Hinweis** und **je Kontext** schätzen.

### 4b. Der erste gelernte „Router“

**Heute** (`gedaechtnis.erinnere`, `gedaechtnis.py:371–423`): Kandidaten = Objekte mit **mindestens einem** passenden
Hashtag (`"(tool:x OR skill:y OR host:z)"`, `intuition.py:82`); Gewicht =
`relevanz (FTS-Rang normiert, sonst 1) + (1+h)^(−0,3) + min(1, w/3·0,6 + log1p(2·bestätigt+zugriffe)/6 − 0,5·widerlegt) + Bonus`
(Z. 417–421; `VERFALL_D = 0.3`, Z. 51). Alle Koeffizienten (0,6; 1/6; 0,5; 0,3; 0,2) sind **gesetzt**, nicht
gelernt; die Anzahl der gemeinsamen Hashtags geht **nicht** ein (OR-Filter, Relevanz = 1 ohne Freiwörter).

**Stufe 1 — Logistische Regression P(ok | Reize, Hinweis):** `X` aus 4a (Paar Handlung × Hinweis), `y2`. Das
gelernte Gewicht je Merkmal ist direkt lesbar („`hinweis:regel` bei `skill:proxmox` senkt die Fehlerquote um …“) —
erfüllt „zureichender Grund“. Score zum Ranken = `P(ok | Reize, Hinweis) − P(ok | Reize, kein Hinweis)` = erwarteter
**Lift**, statt Rang nach Aktualität+Wichtigkeit. Aktualität und Wichtigkeit bleiben als **Merkmale** drin (als
Zahlen-Spalten) — das Modell lernt dann, *wie viel* sie zählen, statt dass wir 0,3 und 0,6 raten.

**Stufe 2 — Kontextueller Bandit:** Das Problem ist kein reines Vorhersageproblem, sondern Auswahl mit Rückmeldung
nur für das Gezeigte. Li, Chu, Langford, Schapire 2010, „A Contextual-Bandit Approach to Personalized News Article
Recommendation“ (https://arxiv.org/abs/1003.0146 **[V]**, WWW 2010): „we model personalized recommendation of news
articles as a contextual bandit problem“ — Kontext = Nutzer-/Artikelmerkmale (bei uns: Reize), Arm = Artikel (bei
uns: Hinweis), Reward = Klick (bei uns: `ok`). **Thompson Sampling** je Hinweis ist die einfachste Umsetzung: je
Hinweis eine Beta(α,β)-Verteilung über „nützt“, α += ok, β += nicht-ok, zum Ranken je Anfrage eine Stichprobe ziehen
— das exploriert automatisch selten gezeigte Hinweise. Quellen: Russo et al. 2017, „A Tutorial on Thompson Sampling“
(https://arxiv.org/abs/1707.02038 **[V]**: „an algorithm for online decision problems where actions are taken
sequentially“, balanciert Ausnutzen und Informationsgewinn); kontextuelle Variante mit Garantien: Agrawal & Goyal
2012 (https://arxiv.org/abs/1209.3352 **[V]**, „the first theoretical guarantees for the contextual version of
Thompson Sampling“). Für Thompson Sampling genügt ein Zähler­paar je Hinweis — kein sklearn, kein Export; es ist die
natürliche Fortsetzung des heutigen `zugriffe`-Zählers (`gedaechtnis.py:242–249`), nur mit Nenner.

**Learning-to-Rank:** Wenn mehrere Hinweise gleichzeitig gezeigt werden (Budget 4, `intuition.py:31`), ist das Ziel
eine Reihenfolge, nicht eine Wahrscheinlichkeit. Joachims, Swaminathan, Schnabel 2016, „Unbiased Learning-to-Rank
with Biased Feedback“ (https://arxiv.org/abs/1608.04468 **[V]**): Klick-Feedback ist durch Position verzerrt
(„position bias in search rankings strongly influences how many clicks a result receives“); Gegenmittel ist
Propensity-Gewichtung im Lernen („Propensity-Weighted Ranking SVM“). Für vi-mcp heißt das: die **Position** des
Hinweises in der Liste und die Tatsache, dass **nur 4 gezeigt** wurden, gehören mit in die Beobachtung.

**Vergleich in einem Satz:** Heute ranken wir nach *wie alt und wie oft bestätigt*; der Router rankte nach *wie oft
ging es danach gut, im Vergleich zu ohne* — dieselbe Information (`gefunden`, `ok`), aber als Zähler mit Nenner bzw.
als gelerntes Gewicht, statt als heuristische Summe.

### 4c. Embeddings und Vektorspeicher

Park et al. 2023, „Generative Agents“, Abschnitt 4.1 (https://ar5iv.labs.arxiv.org/html/2304.03442 **[V]**;
Projektprüfung `docs/FORSCHUNG.md:216`): Relevanz ist „the cosine similarity between the memory's embedding vector
and the query memory's embedding vector“; die drei Werte Recency/Importance/Relevance werden „to the range of [0,1]
using min-max scaling“ normiert und mit Gewicht 1 summiert. **vi-mcp ersetzt diesen Term** durch Hashtag-Filter +
FTS5-Rang (`gedaechtnis.py:396–401, 420`) — exakte Übereinstimmung statt semantischer Nähe. Cosinus über Embeddings
fände „ssh timeout“ auch, wenn der Text „Verbindung hängt“ heißt; FTS5 nicht.

Auf dem Produktivhost gibt es laut `docs/FORSCHUNG.md:431` und `CHANGELOG.md:96` die Route `/health/embed`
(llama.cpp-Stack, `docs/LOKAL.md:8`). Ob dieser Dienst für unsere Texte geeignet ist (Modell, Dimension, Sprache), ist
laut FORSCHUNG.md **ungeprüft** — bleibt **Hypothese**.

**Speichern in SQLite — zwei Wege:**

1. **BLOB float32, ohne Erweiterung:** Spalte `vektor BLOB` (n × 4 Byte, `numpy.float32.tobytes()`), Cosinus in Python
   (`numpy`) über alle Kandidaten nach dem Hashtag-Filter. Bei unseren Größen (Tausende Objekte, Filter vorher) reicht
   das; kein Index nötig. Vorteil: Null neue Abhängigkeit, Format trivial dokumentierbar.
2. **sqlite-vec** (https://github.com/asg017/sqlite-vec **[V]**, API-Abfrage heute): Beschreibung „A vector search
   SQLite extension that runs anywhere!“, pures C ohne Abhängigkeiten, Lizenz Apache-2.0/MIT; 8 247 Sterne, erstellt
   2024-04-20, letzter Push **2026-05-18**, 249 offene Issues, nicht archiviert; letztes Release **v0.1.9 (2026-03-31,
   kein Prerelease)**; Sponsoren Mozilla Builders, Fly.io, Turso u. a.; `pip install sqlite-vec`. README warnt: „sqlite-vec
   is a pre-v1, so expect breaking changes!“ Funktionen (https://alexgarcia.xyz/sqlite-vec/api-reference.html **[V]**):
   `vec_f32(…)` erzeugt „a BLOB with 4 bytes per element“ aus BLOB oder JSON, `vec_distance_cosine(a, b)`,
   `vec_distance_L2`, `vec_normalize`, `vec0`-Virtual-Tables für float/int8/binary mit KNN per `MATCH … ORDER BY
   distance LIMIT k`. **Einordnung:** real und gepflegt, aber pre-1.0 mit ~6 Monaten ohne Push — für einen Ein-Host-
   Dienst mit WAL-SQLite passend, aber die BLOB-Variante (1) ist mit sqlite-vec kompatibel (gleiches float32-Layout),
   man kann also mit (1) anfangen und (2) später als Index darüberlegen, ohne Daten zu wandeln.

Beobachtungspunkt (CLAUDE.md Regel 6): Embedding-Relevanz lohnt sich nur, wenn Treffer *mit* ihr häufiger zu `ok`
führen als ohne — messbar mit demselben `hinweis_lift`, A/B nach Instanz oder Zeitfenster.

### 4d. Was „Training“ ändert — und was nicht

- **Lernt:** der Router (Gewichte der logistischen Regression, Beta-Zähler des Banditen, ggf. Hashtag-Embeddings aus
  `nn.Embedding`). Das sind **unsere** Parameter, in **unserer** Datenbank, jederzeit erklärbar und zurücksetzbar.
- **Lernt nicht:** das Sprachmodell (Claude, Qwen). Seine Gewichte bleiben unverändert; es sieht nur andere Hinweise im
  Kontext. Das ist auch die Trennung Intension/Extension: der Router ist Policy („was zeigen“), das LLM ist Nutzer.
- **Echtes Fine-Tuning (LoRA)** — Hu et al. 2021 (https://arxiv.org/abs/2106.09685 **[V]**): „freezes the pre-trained
  model weights and injects trainable rank decomposition matrices“, reduziert trainierbare Parameter um „10,000
  times“ und GPU-Speicher um „3 times“ gegenüber vollem Fine-Tuning von GPT-3 175B. Wo es *passen* würde: ein lokales
  Modell (Qwen auf <host>) auf **konsolidierte Erkenntnisse** (Art `erkenntnis`/`regel`, geteilt, mit Belegen)
  nachtrainieren, damit es sie ohne Kontextfenster „weiß“. Warum das teuer und riskant ist: (a) es gilt nur für
  Modelle, deren Gewichte wir haben — Claude nicht; (b) jede Änderung einer Erkenntnis erfordert Retraining, während
  der Retrieval-Weg sofort wirkt; (c) **nichts verschwindet still** wird verletzt: eine widerlegte Erkenntnis bleibt im
  Gewicht, ohne Grabstein; (d) Zugangsdaten aus Erfahrungen dürften nie ins Modell (Sicht `privat`,
  `gedaechtnis.py:38`); (e) Messbarkeit: ob das Modell etwas „gelernt“ hat, ist nur über Probe-Batterien prüfbar
  (FORSCHUNG.md:519–522). **Einordnung:** Retrieval + gelernter Router zuerst; LoRA frühestens, wenn der Hinweis-
  Lift stabil positiv ist und ein lokales Modell im Einsatz ist. Die Reihenfolge ist Schätzung, kein Messwert.

---

## 5. Ehrliche Vorbehalte

**Stichprobengröße.** Peduzzi, Concato, Kemper, Holford, Feinstein 1996, „A simulation study of the number of events
per variable in logistic regression analysis“, J Clin Epidemiol 49(12):1373–1379 (Europe PMC, PMID 8970487 **[V]**):
„For EPV values of 10 or greater, no major problems occurred. For EPV values less than 10, however, the regression
coefficients were biased in both positive and negative directions“, Varianzschätzer falsch, 90-%-Intervalle ohne
korrekte Überdeckung. Harrell, *Regression Modeling Strategies* (https://hbiostat.org/rmsc/multivar.html **[V]**,
Abschnitt 4.4): „p should be < m/15“, mit m = begrenzende Stichprobengröße, für binäre Antworten
`3·n·q·(1−q)`. **Für vi-mcp:** „Ereignis“ ist die seltenere Klasse (meist `ok:nein`). Mit ~50 Merkmalen
(Tools × Hosts × Themen × Hinweisarten) braucht Stufe 1 also **≥ 500 Fehlschläge**, nach Harrell ≥ 750 — das ist bei
einem Werkzeug-Hook pro Handlung Wochen bis Monate. Bis dahin ist die Heuristik (oder ein Bandit mit wenigen Armen)
nicht nur ausreichend, sondern **besser**: ein Modell unter 10 EPV liefert verzerrte Gewichte mit falscher Sicherheit.
`messung.MINDESTENS = 10` (`messung.py:14`) ist dieselbe Regel in Miniatur.

**Rückkopplung / Off-Policy.** Der Router entscheidet, **was gezeigt wird**; Labels entstehen nur für Gezeigtes. Ein
Hinweis, der nie gezeigt wird, kann nie als nützlich auffallen (heute schon: nur 4 von n, `intuition.py:97–99`). Das
ist das „partial-label“-Problem: Li, Chu, Langford, Wang 2011, „Unbiased Offline Evaluation of Contextual-bandit-based
News Article Recommendation Algorithms“ (https://arxiv.org/abs/1003.5956 **[V]**, WSDM 2011): Offline-Bewertung ist
schwer „because of their partial-label nature“; Lösung ist eine „replay methodology“, die „provably unbiased
evaluations“ liefert — sie setzt voraus, dass die **geloggte Policy zufällige Anteile** enthält. Dudík, Langford, Li
2011, „Doubly Robust Policy Evaluation and Learning“ (https://arxiv.org/abs/1103.4601 **[V]**): „the past data
typically does not faithfully represent proportions of actions taken by a new policy“; Reward-Modell allein ist
verzerrt, Propensity-Modell allein hat hohe Varianz, doppelt robust kombiniert beides. Bottou et al. 2013,
„Counterfactual Reasoning and Learning Systems“ (https://arxiv.org/abs/1209.2355 **[V]**): kausale Inferenz für
Lernsysteme, die mit ihrer Umgebung interagieren (Bing-Anzeigenplatzierung).
**Konsequenz für vi-mcp — Beobachtungspunkte:**
1. Jede Erfahrung muss **die Propensity** mitführen: Welche Kandidaten gab es, welche wurden gezeigt, mit welchem
   Score/Rang (heute: `gefunden` ja, Kandidatenmenge und Rang nein → kleine Ergänzung in `intuition.vorher`).
2. Ein **ε-Anteil zufälliger Hinweise** (z. B. 10 %, als `exploration:ja` markiert — benannt, nicht still), sonst ist
   keine unverzerrte Bewertung einer neuen Rangfolge möglich.
3. Der Vergleich „mit vs. ohne Hinweis“ (`hinweis_lift`) ist **nicht kausal**: ob ein Hinweis gezeigt wird, hängt davon
   ab, ob es zum Werkzeug schon Wissen gibt — Werkzeuge mit Wissen sind vermutlich auch die häufiger genutzten und
   besser verstandenen (Confounder). Das ist post hoc (CLAUDE.md Regel 5); nur Randomisierung (Punkt 2) löst es.

**Weitere Grenzen:**
- Labels sind grob: `ok` misst den Werkzeugaufruf, nicht ob der Hinweis gelesen oder befolgt wurde (Annahme laut
  `ARCHITEKTUR.md:137–140`).
- Nichtstationarität: Hosts, Tools und Fehlerbilder ändern sich; ein Modell braucht Zeitfenster oder Vergessen — der
  Bandit hat das über Zähler-Abklingen, die Regression nur über Neutraining.
- Privatsphäre: der Export enthält `host:`-Namen und Hinweis-IDs, aber **keine** Ergebnisse — `daten.vorher` ist
  sicher, `ergebnis`/`fehler`-Texte dürfen nicht in Merkmale (Sicht `privat`, `gedaechtnis.py:38`).
- Nicht geprüft (Hypothesen): Eignung des `/embed`-Dienstes; JSON1-Verfügbarkeit im Produktions-Python; ob sqlite-vec
  auf Ubuntu 24.04/Python 3.12 des Hosts lädt.

---

## Quellenliste (Kurzform)

Web **[V]**: scikit-learn getting_started · glossary · datasets.html · datasets/loading_other_datasets.html ·
modules/feature_extraction.html · modules/preprocessing.html · GitHub scikit-learn `main` (validation.py,
_dict_vectorizer.py, _hash.py, _openml.py, _base.py) · jaketae.github.io/study/sklearn-pipeline · docs.pytorch.org
data_tutorial, quickstart_tutorial, torch.nn.Embedding (2.15) · arXiv 1003.0146, 1003.5956, 1103.4601, 1209.2355,
1209.3352, 1608.04468, 1707.02038, 2106.09685, 2304.03442 (ar5iv) · Europe PMC PMID 8970487 · hbiostat.org/rmsc/
multivar.html · github.com/asg017/sqlite-vec + api.github.com + alexgarcia.xyz/sqlite-vec/api-reference.html.
Nicht erreichbar heute: nowpublishers INR-016 (Liu 2009, 403), NeurIPS 2011 Chapelle & Li (Proxy), MSR-TR-2010-82
(Burges, PDF nicht lesbar) — ersetzt durch Joachims 2016, Russo 2017, Agrawal & Goyal 2012.

Projekt **[V]**: `docs/ARCHITEKTUR.md` (Z. 58, 102–117, 137–143) ·
`vi_mcp/gedaechtnis.py` (Z. 38, 51, 99–106, 242–249, 331, 371–423) · `vi_mcp/intuition.py` (Z. 31, 47, 82, 97–99,
109, 160, 188–206) · `vi_mcp/messung.py` (Z. 14–37) · `docs/FORSCHUNG.md` (Z. 216, 272, 431, 519–522) ·
`CHANGELOG.md:96` · `docs/LOKAL.md:8`.
Test **[V]**: `…/scratchpad/exporttest/{mach_db.py, export_beobachtung.py, vi-test.db, beob.X.npz, beob.meta.npz}`,
ausgeführt 2026-11-08 13:28 lokal (Python 3.12.3, numpy 1.26.4, scipy 1.11.4; sklearn/torch nicht installiert).
