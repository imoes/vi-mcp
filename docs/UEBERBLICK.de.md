# Überblick für den Nutzer: Wissen, Ziele und Entscheidungen (Stand 25.11.2026)

Diese Seite fasst zusammen, was im Gespräch mit dem koordinierenden Claude erklärt wurde, damit es nachlesbar bleibt.
Jede Zahl nennt ihre Quelle (Commit, Dokument oder VI-Eintrag). Die Zieltabelle mit dem aktuellen Stand steht in
[GOALS.md](GOALS.md). Diese Seite erklärt die Hintergründe.

---

## 1. Trainiertes Wissen und RAG: technisch

**In einem Satz:** Bei trainiertem Wissen steckt der Fakt in den Gewichten des Modells. Bei RAG liegt er als Text in der VI und wird
erst zur Frage gesucht und in den Prompt gelegt.

### Trainiertes Wissen (Fine-Tuning, z. B. LoRA)

- **Speicherort:** Gradientenabstieg verändert die Gewichte so, dass das Modell die Fakten der Trainingstexte wahrscheinlicher
  erzeugt. Bei LoRA sind das kleine Zusatzmatrizen (run 3: etwa 10 Mio. Parameter, 40 MB Datei).
- **Abruf:** Das Modell erzeugt die Antwort aus den Parametern. Es gibt keinen Nachschlagevorgang und keine Quelle, auf die man zeigen kann.
- **Ändern und löschen:** nur durch neues Training. Einen einzelnen Fakt gezielt entfernen geht nicht.
- **Typischer Fehler:** Das Modell weiß nicht, was es nicht weiß. Der trainierte run 3 hat sich nie enthalten und hat Hosts und IPs
  erfunden.
- **Gemessen:** Wissensprobe mit 60 Fragen zu trainierten Dokumenten: Basis 0 richtig, run 3 7 richtig und 9 teilweise
  (FINETUNING_PAPER, run 3).

### RAG (so arbeitet die VI)

- **Speicherort:** Als Textobjekt in der VI-Datenbank, mit Quelle, Sichtbarkeit und Änderungshistorie. Das Modell bleibt unverändert.
- **Abruf:** `vi_recall` sucht zur Frage:
  - Volltextsuche (BM25) und Bedeutungssuche (Embedding bge-m3) laufen parallel;
  - Rank Fusion führt beide Listen zusammen;
  - ein Cross-Encoder sortiert die besten Treffer neu;
  - die Treffer kommen in den Prompt, und das Modell liest sie dort.
- **Ändern und löschen:** sofort. `vi_learn` legt an; ein Löschen hinterlässt einen Grabstein. Rechte gelten pro Objekt.
- **Typische Fehler:**
  - Die Suche findet das Richtige nicht. Bei Zwei-Schritt-Fragen standen beide Seiten nur in 6,4 % der Fälle unter den ersten 4
    Treffern (Z6).
  - Das kleine Modell liest den gefundenen Text falsch (Fehlbindungen in Z5).
- **Kosten:** pro Frage Embedding und Reranking, zurzeit 2–6 s. Kein Training.

### Dazwischen: der kNN-Speicher (Z11)

- **Funktionsweise:** Das Modell bleibt eingefroren. Daneben liegt ein Speicher aus „Zustand → nächstes Token“. Bei jedem Token mischt
  das Modell seine Vorhersage mit den nächsten Nachbarn aus dem Speicher.
- **Vorteile:** ändern und vergessen ohne Training; die Herkunft ist ablesbar.
- **Nachteil:** Er arbeitet nur auf Token-Ebene und versteht keine Dokumente.

### Direkter Vergleich (Z11, 297 Fragen, blinde Bewerter)

| Weg | richtig | teilweise | falsch |
|---|---|---|---|
| ohne Wissen | 5 | 17 | 275 |
| LoRA (trainiert) | 42 | 41 | 214 |
| kNN-Speicher | 44 | 41 | 212 |
| **RAG** | **161** | 80 | 56 |

Quelle: Z11-Sekundärsatz, nachgezählt am 23.11.2026; siehe [GOALS.md](GOALS.md), Statuslog Z11.

**Folge:** Entscheidung des Nutzers vom 24.11.2026 (VI insight:b04c8df5): Die VI bezieht ihr Wissen weiter über RAG, nicht über
Fine-Tuning und nicht über den kNN-Speicher.

**Merksatz:** Training verändert, *wie* das Modell denkt und formuliert. RAG bestimmt, *was* es zur Frage vor Augen hat. Fakten
gehören in die VI; Fähigkeiten (lesen, übersetzen, Format, Pflichten) gehören ins Training.

---

## 2. Wie wir den Unterschied überbrücken

Mehr Fakten passen kaum ins kleine Modell (LoRA 42 von 297). Der Engpass liegt woanders: im **Finden**, im **richtigen Lesen** und im
**Eingestehen von Nichtwissen**. Deshalb vier Wege:

1. **Das Modell trainieren, gefundene Texte richtig zu lesen.** Trainiert wird mit Frage, gefundenen Absätzen samt Störabsätzen und
   richtiger Antwort mit Beleg. Das Modell lernt, Störabsätze zu ignorieren, nicht die Fakten selbst.
   - Literatur: RAFT, Zhang et al. 2024, arXiv 2403.10131. Aus dem Gedächtnis zitiert und noch nicht im Volltext geprüft.
   - Bei uns: In I1 entschied ein fremder Absatz 8 falsche Antworten; in Z5 waren beide Verluste Fehlbindungen. Passt zu Z1 und Z8.
2. **Auf „weiß ich nicht“ trainieren.** Ohne Beleg soll das Modell „unbekannt“ sagen, statt zu raten.
   - Literatur: Gekhman et al. 2024, arXiv 2405.05904 (Training auf neue Fakten fördert Erfindungen). Aus dem Gedächtnis zitiert.
   - Bei uns: Die Philosophie-Saat (Z4) unterscheidet geprüfte und ungeprüfte Quellen. I3′ testet das an echten Quellen.
3. **Die Suche verbessern, nicht das Modell.**
   - Z6: „Anker + Sprung“ findet beide Seiten zu 81,1 % statt 6,4 %. Der Einbau in vi-mcp 0.72.0 läuft.
   - Später: Das Modell lernt, gute Suchanfragen an die VI zu stellen. Daten dafür sammelt vi-mcp schon (`search_questions`).
4. **Wissen in prüfbare Fakten übersetzen.** Der Reader macht aus dem Text clingo-Fakten mit Quelle, und clingo leitet ab. So ist
   genau prüfbar, worauf eine Antwort beruht: I1 zeigt, dass 97,2 % der richtigen Antworten nur auf Belegabsätzen beruhen.

**Was nach Messung nicht hilft:**

- Fakten per LoRA einspeisen.
- Den kNN-Speicher zu RAG mischen. Beim alten Gewicht schadet das (20 statt 161 richtig); beim abgestimmten Gewicht gibt es keinen
  Vorteil gegenüber RAG allein (Vorzeichentest 2:7, p 0,18; Z11 A4).

---

## 3. Ist die symbolische Variante schon in der VI?

**Teilweise.**

| Teil | Stand | Beleg |
|---|---|---|
| `vi_logic`: clingo über Objekte, Hashtags und Kanten; das Server-LLM schreibt das Programm; vierwertige Antworten | **in Produktion** | Produktionskopie 13.11.2026: 15 von 16 Beziehungsfragen exakt, mit Suche allein 2 von 16 (vi-mcp README, „Logic over the memory“; PAPER.md §5.6) |
| `clingo-object` (Python-Paket), Philosophie-Pakete, `vi_machine` | in Produktion | vi-mcp README |
| **Reader:** Seiten-*Inhalt* → clingo-Fakten mit Quelle | **nur Forschung** | Z1 (75,5 %), Z8 RAG-1c |
| Symbolischer Antwortweg mit Herkunftsnachweis | **nur Forschung** | I1 (97,2 %), I2 |
| Faktenblock vor der AIKB-Antwort (Z5) | **verworfen** am 24.11.2026 | SUMMARY_Z5; kein inhaltlicher Gewinn |

**Geplant (Entscheidung 25.11.2026, VI insight:11b3df70):**

- Die VI antwortet weiter per RAG und bekommt eine **symbolische Herkunftsprüfung**.
- Der Reader macht aus den gefundenen Absätzen Fakten mit Quelle; clingo zeigt, welche Absätze die Antwort tragen.
- Hängt eine Antwort an einem fremden Absatz oder an keinem, wird sie markiert.
- Eine Session (7a) schreibt den Plan „I4“ mit Architektur und einer Messung an echten VI-Fragen vor jedem Bau.
- Gebaut wird erst nach weiterer Freigabe.

**Plan I4** (25.11.2026, vi-mcp Branch z11-integration f93fd7b, docs/PLAN_I4_VI_SYMBOLIC.md):

- **Wichtige Tatsache:** Die VI schreibt keine Antworten selbst. `vi_recall` liefert Treffer, und der aufrufende Agent antwortet.
  Eine Prüfung braucht also dessen Antwort.
- **Empfehlung: C + B.**
  - **C:** Der Reader liest Fakten pro Objekt offline, beim Import oder im Schlafzyklus. Die Fakten erben Sichtbarkeit und
    Löschung vom Objekt.
  - **B:** Ein eigenes Werkzeug `vi_verify(Frage, Antwort, zitierte Objekte)` liefert eines von vier Urteilen:
    gestützt (mit Absatz) / nicht gestützt / beruht auf anderer Entität / nicht prüfbar.
- **Messung vor dem Bau:**
  - Fragen: echte VI-Fragen aus Z5 (178 und 118), dazu die Zwei-Schritt-Fragen aus Z6.
  - Vergleich gegen drei Basislinien: RAG ohne Prüfung, Stringvergleich, Selbstprüfung per LLM.
  - Gebaut wird nur, wenn die Prüfung beide aktiven Basislinien schlägt, ohne mehr Fehlalarme, und eine Mindestreichweite
    erreicht (Vorschlag: 30 %).
- **Risiken:** geringe Reichweite des Readers (Z5: 14–49 von ~120), Lesefehler werden zu Fehlalarmen, die vermutete Fehlmaskierung
  (zuerst prüfen), Bewerter aus derselben Modellfamilie.
- **Aufwand:** Messung etwa 2 Session-Tage plus 2–3 GPU-Stunden. Der Bau danach etwa 7–10 Session-Tage.

---

## 4. Z2 im Detail: Regeln finden (symbolische Regression)

- **Aufgabe:** Eine kleine Welt aus Fakten plus das gewünschte Ergebnis, z. B. „welche Bücher sind überfällig“. Gesucht ist die
  clingo-Regel, die es erzeugt und auch auf neuen Welten stimmt.
  - Gemessen wird, wie viele Auswertungen ein Suchverfahren bis zur ersten geprüft exakten Regel braucht.
  - Die Testaufgaben schreibt jeweils ein unabhängiger Autor-Agent, blind.
- **Suchverfahren:**
  - **gp2** (genetische Programmierung): schnelle Startphase; löst einfache Aufgaben oft in 1–6 Versuchen.
  - **binder-G** (baut Regeln systematisch auf): bei manchen schweren Aufgaben um Größenordnungen schneller (394 statt 13.170
    Auswertungen), bei einfachen langsamer.
- **Ziel:** bei ≥ 35 von 40 blinden Aufgaben weniger Auswertungen als gp2.
- **Bisher:**
  - binder-G allein scheiterte zweimal (g8e: 14 weniger / 18 mehr / 8 gleich; p 0,59). Damit endet der Ansatz; gp2 bleibt
    Regelfinder.
  - Das Portfolio „gp2-Startphase, dann binder“ (P2) ist auf g8f signifikant besser als gp2 (Holm-p 0,0094; sr-binder 3977b57). Das
    Ergebnis hängt aber an einer Auslegung des Vorabplans (fb414bb).
  - 35/40 ist mit diesen beiden Verfahren nicht erreichbar: Selbst die nachträglich beste Wahl je Lauf schafft 21/40. Sechs Aufgaben
    löst keines.
- **Neu: ein Sprachmodell als Vorschlagender, clingo prüft.**
  - **T1:** Löst qwen3.8 als Lehrer Aufgaben, an denen beide Verfahren scheitern? Ab 2 solchen Aufgaben folgt Destillation.
    Abschluss am 25.11.2026 abends.
  - **L1:** Das 0,6B-Modell lernt, in einer Schleife mit clingo vorzuschlagen und nach Gegenbeispielen zu reparieren. Die Daten
    sind gebaut (79.592 Zeilen). Training erst nach Freigabe mit dem T1-Ergebnis.

## 5. Z9 im Detail: Wörter als Symbole (W-Lab)

- **Frage:** Lernt ein von Grund auf trainiertes Kleinmodell die Bedeutung eines Wortes aus dem Gebrauch, oder nur den Namen
  auswendig? Daten: Wiktionary-Bedeutungen mit Beispielsätzen, Englisch und Deutsch.
- **Test:** Zu einer nie gesehenen Bedeutung vier Erklärungen zur Auswahl; Zufall ist 0,25.
- **WG1 (erreicht):** Englisch 0,453, Deutsch 0,345. Mit vertauschten Symbolen fällt der Wert auf Zufall (0,254): Das Modell nutzt
  die Bedeutung, nicht die Form.
- **WG2 (deutsche Beugung):** Hypothesen 1–3 halten; Hypothese 4 ist nicht bestätigt (p 0,051). Der Nachtest WG2-X zeigt: Der
  Unterschied kommt von der Darstellung der Testfragen (p 0,005), nicht vom Training (p 0,44).
- **WG3 (läuft):** qwen27b schreibt als Lehrer je fünf neue deutsche Beispielsätze pro Bedeutung. Das Kleinmodell lernt damit und
  wird auf echten, zurückgehaltenen Sätzen getestet. Verlängert, bis 2.000 Datensätze erreicht sind, längstens bis 26.11.2026 06:00
  UTC; danach Arm L.
- Paper: W_LAB_PAPER.md §14–16.

## 6. Z6: wie die Erkenntnis angewendet wird

- **Ergebnis:** Nennt eine Frage einen Hostnamen, findet „Seite mit diesem Namen im Titel, dann die dort erwähnten Hosts“ beide
  nötigen Seiten zu 81,1 % statt 6,4 % (PREREG_Z6 2e846bb).
- **Lehre aus Z5:** Leichter finden bringt noch keinen inhaltlichen Gewinn. Gemessen werden muss, ob Antworten besser werden.
- **Umsetzung (freigegeben 25.11.2026):**
  1. vi-mcp 0.72.0 mit Schalter (Standard: aus), mit Sichtbarkeitsprüfung und höchstens 1–2 Sprungseiten vor den normalen Treffern.
  2. Offline-Prüfung mit Vorabplan, gepaart auf derselben Produktionskopie: Schalter aus gegen an, mit demselben Fragenkatalog
     (`eval/recall.json`).
  3. Danach im Betrieb messen, ob Agenten die Treffer öfter nutzen.

---

## 7. Entscheidungen vom 25.11.2026 (Abschlusstag)

- Ergebnisse kommen ins jeweils passende **bestehende** Paper; ein neues nur, wenn keins existiert. Zuordnung:
  - DIVISION_OF_LABOUR_PAPER: Z1, Z2, Z3, Z8, Z12 (zugleich das BabyLM-Paper Z10)
  - FINETUNING_PAPER: Z4, Z11
  - W_LAB_PAPER: Z9
  - vi-mcp PAPER.md: Z5, Z6, Z7
- **Z1:** geht weiter (Probelauf mit Stichproben des Readers).
- **Z3:** Neuer Ansatz Z3-G (Dekodierung nur aus gegebenen Fakten) ohne Gewinn (0,7273 gegen 0,7270). Danach **pausiert**: Das Lesen
  einer gegebenen Regel übernimmt clingo; das testet Z12 Arm G.
- **Z4:** Recherche, dann Schritt 0 (run 35, Seed 43) und kit36 freigegeben.
- **Z6:** Einbau als vi-mcp 0.72.0 freigegeben.
- **Z7:** Kopie der Produktionsdatenbank freigegeben. Befund: Der AUC-Sprung kommt von Ausfällen beim LLM-Anbieter von CentralStation
  (HTTP 402 „insufficient credits“, 405), nicht vom Nutzen der Hinweise.
- **Z11:** integriert die Erkenntnisse aus Z1 und Z4 (I1, I2 erledigt; I3′ heute Nacht auf der 3060; Plan I4).
- **Z12 neu: „Denken in clingo“.** S0: Das untrainierte 0,6B löst in Prosa 16/100, mit clingo-Schleife 5/100. S1 Teil A
  (Kleinmodell) läuft auf der 3060; Teil B (Qwen) folgt auf der 3070 ab 27.11.
- **Z5 und Z11 geschlossen** am 24.11.2026.

## 8. Wo der aktuelle Stand steht

- Zieltabelle: [GOALS.md](GOALS.md)
- GPU-Plan: VI-Eintrag `schedule:gpu`
- Status je Strang: VI-Einträge `status:<strang>` (z. B. `status:z3`, `status:z11-virtual-llm`)
- Tagesordnung des Abschlusstags: VI-Eintrag `agenda:2511-consolidation`
