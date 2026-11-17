# vi-mcp — ein Gedächtnis für KI-Agenten, das behält, was sie lernen

**Deutsch** · [English](README.md) · [Changelog](CHANGELOG.md) · [Download](https://github.com/imoes/vi-mcp/releases/latest) · [Alle Dokumente](docs/README.md) · [![Release](https://img.shields.io/github/v/release/imoes/vi-mcp?label=release)](https://github.com/imoes/vi-mcp/releases/latest)

`vi-mcp` ist eine **VI (virtuelle Intelligenz)**: ein Serverprozess mit einem Gedächtnis, mit dem sich KI-Agenten — Claude Code,
Codex, Hermes oder jeder andere MCP-Client — über **MCP (Streamable HTTP)** verbinden. Was ein Agent herausfindet, entscheidet oder
korrigiert bekommt, wird als lesbares Objekt mit Quelle gespeichert und kommt als Hinweis zurück, kurz vor der nächsten Handlung, für
die es zählt.

## Für wen

**Ein einzelner Agent.** Eine einzelne KI vergisst: Das Kontextfenster endet, eine Sitzung schließt, das Gespräch wird verdichtet, das
Modell wird ausgetauscht. Mit vi-mcp wird ihr Wissen **außerhalb des Modells konserviert** — jede Lösung mit den Befehlen, die
funktioniert haben, jede Entscheidung, die du getroffen hast („ab jetzt …“), jede nachgeschlagene Tatsache, mit Quelle und Datum. Die
nächste Sitzung, der nächste Tag oder ein anderes Modell beginnt damit. Falsches Wissen wird mit Begründung widerlegt, nicht still
überschrieben.

**Viele Agenten.** Sitzungen teilen dasselbe Gedächtnis zur selben Zeit, jede mit ihrem eigenen Kontext, wie Zeitscheiben auf einem
Prozessor. Was eine Sitzung gelöst hat, ist ein Hinweis für die nächste, auch mit einem anderen Modell oder Hersteller. Keine Instanz
kann ihr eigenes Wissen bestätigen; das prüfen andere.

**In die Gewichte eines Modells.** Was eine VI gelernt hat, lässt sich **in ein Modell trainieren**, wenn du es entscheidest. Das
Gedächtnis speichert sein Wissen von Anfang an trainingsfertig (belegte Frage-Antwort-Paare und eine nie trainierte Prüffrage je
Objekt), misst, wann es reif ist (der Inkubator), und schreibt ein vollständiges Fine-Tuning-Kit (Daten, Skripte, Auswertung) für einen
GPU-Rechner. vi-mcp trainiert nie von selbst.

*Gemessen:* Ein 0,6B-Modell, feinjustiert auf 500 Dokumente einer VI, beantwortete 7 von 60 nie trainierten Prüffragen dazu richtig
und 9 teilweise, das Grundmodell 0 und 5 (blind, Vorzeichentest p = 0,008; 15.11.2026). Die Suche im Gedächtnis findet bekanntes
Wissen mit MRR 0,735 über Bedeutung plus Volltext, gegen 0,364 nur mit Volltext (Produktion, 12.11.2026).

## Schnellstart

```bash
# Debian / Ubuntu — signiertes Paket-Repository, spätere Updates kommen mit apt upgrade
curl -fsSL https://imoes.github.io/vi-mcp-packages/setup.sh | sudo sh && sudo apt install vi-mcp
sudo vi-mcp setup            # Menü: richtet Claude Code, Codex CLI, Hermes Agent und den Hook ein, ein Token je Programm
```

Danach arbeitest du wie gewohnt. Vor einer Handlung ruft der Agent `vi_before` und bekommt höchstens vier Hinweise, danach `vi_after`;
mit dem Claude-Code-Hook geschieht das von selbst. Sag ihm, er soll sich etwas merken, und er ruft `vi_learn`. Alle Plattformen
(Fedora/RHEL, Arch, macOS, Windows) stehen unter [Installieren](#installieren).

## Wie es funktioniert

```
 Sitzung A (Claude Code)   Sitzung B (Codex, Hermes)   Sitzung C (Hook)
        │  Mcp-Session-Id         │                           │
        └────────────── POST /mcp (Bearer-Token je Instanz) ──┘
                                  │
                     ┌────────────▼─────────────┐
                     │  vi-mcp  (EIN Prozess)    │
                     │  vorher · nachher · Schlaf│
                     └────────────┬─────────────┘
                                  │ ein Schreiber
                           vi.db (SQLite oder PostgreSQL)
```

- **Objekte, keine Notizen.** Alles ist ein Objekt mit Hashtags (`art:wert`), Autor und Sichtbarkeit — privat, geteilt oder intern
  (nur mit Token; nie in ein offenes Netz, nur in ein Firmennetz): Erfahrung, Erkenntnis, Regel, Skill, Bewertung.
- **Vor jeder Handlung** (`vi_before`) bekommt eine Sitzung höchstens vier Hinweise, die einen Host, ein Programm oder einen Fehler mit
  ihrem Vorhaben teilen. Ein Hinweis wird erst verstärkt, wenn die Handlung danach gelingt.
- **Vor jeder Frage** bringt der Hook das passende Wissen zu deinem Prompt, auch bei Nachfragen (Claude Code `UserPromptSubmit`,
  Hermes `pre_llm_call`). Der Prompt wird maskiert und nicht gespeichert.
- **Schlaf.** Wenn genug passiert ist, verdichtet der Server Erfahrungen zu Erkenntnissen und Skills, vergleicht neue Belege mit dem
  Bekannten, führt Wiederholungen zusammen und archiviert, was niemand nutzt (weiter auffindbar).
- **Bewerter.** Code-Regeln, ein Sprachmodell und du beurteilen, ob Arbeit gelungen ist — „das Werkzeug ist nicht abgestürzt“ allein
  sagt das nicht.
- **Lernen.** Aus diesen Ergebnissen lernt ein kleines Modell (der Router), welcher Hinweis in welcher Lage hilft. Er trainiert etwa
  eine Minute nach neuen Erfahrungen neu, in unter einer Sekunde.

### Die Arten von Gedächtnis

| Menschliches Gedächtnis | vi-mcp | Woher es kommt |
|---|---|---|
| episodisch — „was geschah“ | Erfahrung: jede gemeldete Handlung mit Werkzeug, Argumenten, Ergebnis, Dauer | der Hook, automatisch |
| semantisch — „was ich weiß“ | Erkenntnis, Regel: eine Kernaussage plus der vollständige Inhalt und seine Quelle | `vi_learn`, Importe, Schlaf |
| prozedural — „wie es geht“ | Skill: Problem, Schritte, Anleitung, Versionen | `vi_solved`, Schlaf |
| Hinweisreize | Hashtags `art:wert` (`tool:`, `host:`, `topic:` …) und gelernte Suchen | überall |

Erinnern geht über Hinweisreize: Werkzeug, Host und Themen einer Handlung sind ihre Auslöser, und höchstens vier Hinweise antworten
(das Arbeitsgedächtnis hält etwa vier Einheiten, Cowan 2001). Vorgaben, die du machst (`topic:requirement`), stehen im Index, den jede
Sitzung bekommt. Ungenutztes Wissen verblasst und wandert ins Archiv; nichts geht still verloren — zurückgehaltene Hinweise,
zusammengeführte Dubletten und widerlegtes Wissen werden gezählt und benannt.

### Warum das Wissen im Gedächtnis bleibt und nicht im Modell

- **Sofort gelernt.** Wissen ist vor der nächsten Handlung verfügbar, nicht nach dem nächsten Trainingslauf.
- **Jede Erinnerung ist prüfbar.** Sie hat eine Quelle (Befehl, Host und Zeit oder URL), einen Autor und eine Geschichte; sie kann
  bestätigt, bestritten und widerlegt werden — von *anderen* Instanzen.
- **Sie kann vergessen werden.** Lösch ein Gespräch, eine Instanz oder ein Objekt, und es ist weg, mit einem Grabstein, der das sagt.
  Wissen in Modellgewichten lässt sich so nicht entfernen.
- **Vollständig, nicht zusammengefasst.** Code, API-Tabellen und Befehle werden ganz gespeichert: Was im Gedächtnis fehlt, ist eine
  Lücke.
- **Training bleibt möglich.** Weil das Wissen lesbar und mit Quelle bleibt, lässt es sich später immer noch in ein Modell trainieren
  — gemessen, und nur wenn du es entscheidest ([Ein Modell trainieren](#ein-modell-aus-dem-gedächtnis-trainieren)).

### Was es lernt — und warum diese Gewichte keine Tatsachen erfinden können

Die gelernten Gewichte von vi-mcp entscheiden, **welche** Erinnerung gezeigt wird, nie, **was** wahr ist:

- **Der Router** ist eine logistische Regression (scikit-learn). Jede Handlung ist eine Beobachtung: die Auslöser der Lage × die
  gezeigten Hinweise, mit dem Etikett, ob die Handlung gelang. Seine Gewichte sind lesbares JSON (`vi_model`); `vi_why` erklärt, warum
  ein Hinweis kam. Ein neues Modell geht nur live, wenn es das alte auf zurückgehaltenen Daten schlägt, und feste Regeln melden Gewichte,
  die falsch aussehen. Eine KI kann ihn formen, ohne eine Zahl zu schreiben: `vi_feature_propose` liest die Gewichte und die schlechtesten
  Lagen des Routers und schlägt Merkmalsregeln vor; der Schlaf behält nur, was den Router auf zurückgehaltenen Daten verbessert.
- **Der Bandit** (Thompson-Sampling) zählt je Hinweis, wie oft eine Handlung danach gelang, gegen die Grundrate — der Ersatz, solange der
  Router zu wenig Daten hat.
- **Bedeutung** kommt aus einem vortrainierten Embedding-Modell (bge-m3) für die semantische Suche; eine gelernte Gewichtung je Dimension
  der Suchanfrage (`query_adapter`) schaltet sich nur ein, solange ihr Offline-Test sagt, dass sie hilft.

Das Etikett ist das Ergebnis echter Arbeit, also muss niemand Daten beschriften. Das Modell ist Kilobytes groß, über benannte Merkmale
erklärbar und kann nur Erinnerungen ordnen, die es gibt und die eine Quelle haben — ein falsches Gewicht zeigt einen weniger hilfreichen
Hinweis, es kann keine falsche Aussage erzeugen.

*Gemessen (Produktion):* Der Router erkennt Handlungen, die scheitern werden — 51 % der gewarnten Handlungen scheiterten, 3 % der
anderen (AUC 0,88, 12.11.2026). Im randomisierten Vergleich schlug der gewählte Hinweis einen zufälligen um 12,6 ± 5,3 Punkte Erfolg
(12.11.2026); das Prüffenster vom 14.11.2026 zeigt 4,7 ± 3,1 Punkte — für sich allein nicht schlüssig. Ob Hinweise überhaupt den Erfolg
heben, misst ein zufälliges Zurückhalten bei 5 % (`vi_stats`); das braucht Wochen an Daten.

## Ein Modell aus dem Gedächtnis trainieren

Fine-Tuning ist die ausdrückliche Entscheidung eines Menschen; vi-mcp bereitet es vor und misst es, das Training läuft auf einem
GPU-Rechner deiner Wahl.

1. **Wissen wird trainingsfertig gespeichert.** Im Schlaf schreibt der Server belegte Frage-Antwort-Paare und eine nie trainierte
   Prüffrage auf jedes Wissensobjekt (`vi-mcp classify --pairs`).
2. **Der Inkubator sagt, wann eine VI reif ist** — gemessen, nie behauptet: `vi-mcp incubator status [--index X]` (oder `vi_incubator`)
   zeigt jedes Kriterium mit Schwelle, Wert und Zustand (erfüllt, offen oder nicht gemessen — nie als erfüllt gezählt):

   | Kriterium | gemessen als | Standardschwelle |
   |---|---|---|
   | knowledge | geteilte oder interne Wissensobjekte | 500 |
   | checked | Anteil, der nach dem Zeigen bewertet oder von einer Instanz bestätigt wurde | 20 % |
   | search | hybride MRR des täglichen festen Fragensatzes | 0,6 |
   | router | Hinweismodell aktiv, AUC auf zurückgehaltenen Daten | 0,75 |
   | hints_no_harm | das randomisierte Zurückhalten zeigt nicht, dass Hinweise den Erfolg senken | untere 95-%-Grenze über −0,02 |
   | labels | Anteil klassifiziert für die KI-Sprache, und das Schülermodell aktiv | 50 % |
   | training_data | Frage → Antwort-Beispiele, Auswertung zurückgehalten | 1000 |

3. **Sag deiner KI „Ich will feintunen“.** Sie ruft `vi_finetune`, das sagt, ob die VI reif ist, und die Schritte nennt;
   `vi_finetune(action="skill")` ist ein Schritt-für-Schritt-Runbook, das auch kleine Modelle befolgen können
   ([docs/FINETUNING_SKILL.md](docs/FINETUNING_SKILL.md)).
4. **Das Kit.** `vi-mcp finetune kit DIR --base MODELL` schreibt alles, was ein GPU-Rechner braucht: Daten mit Datenblatt, einen
   zurückgehaltenen Testteil, `train.py` (TRL + LoRA), eine [Token-Prüfung und einen Preflight mit dem echten Trainer](docs/TRAINING_PREFLIGHT.md)
   (kein stilles Abschneiden, null Optimiererschritte), `probe.py` (hat das Modell gelernt, worauf es trainiert wurde), `evaluate.py` und
   `convert.sh` (GGUF-Adapter für llama.cpp). `vi-mcp finetune record DIR` hält den Lauf mit seiner Herkunft fest; er gilt nur als
   übernommen, wenn er messbar besser war.

Von null an, mit jedem Befehl: [docs/FINETUNING.md](docs/FINETUNING.md).

**Philosophie-Pakete** geben einer KI Prinzipien ([Philosophien](#philosophien--prinzipien-nach-denen-eine-ki-arbeitet-und-wann-welche-gilt));
ein Kit mit `--philosophy NAME` trainiert ein Modell darauf. Wie ein 0,6B-Modell einen solchen Samen lernt, Lauf für Lauf und vom
Solver bewertet:
[docs/FINETUNING_PAPER.md](docs/FINETUNING_PAPER.md).

## Logik über das Gedächtnis: clingo-object

Suchen bleibt SQL; Schließen über die Objekte des Gedächtnisses ist Antwortmengenprogrammierung mit
[clingo](https://pypi.org/project/clingo/).

**In Alltagssprache fragen** — das Sprachmodell des Servers schreibt das Programm, der Server löst es mit dem, was du sehen darfst:

```text
vi_logic(action="answer", question="Which DMZ hosts are never described as production?")
→ state: answered · 2 answer(s) · 1 round(s) · evidence: inferred
program:
dmz(H) <= (O in objects("netz:dmz")) & (O.host == H)
prod(H) <= (O in objects("kritikalitaet:prod")) & (O.host == H)
ans(H) <= dmz(H) & ~prod(H)
```

**Oder die Regeln selbst schreiben**, in einer Python-ähnlichen Notation (gelesen, nie ausgeführt): `(O in objects("filter"))` bindet
Objekte einer Suche, `(O.host == H)` liest einen Hashtag, `linked(O, B)` folgt einer Kante, `never(…)` meldet eine Verletzung,
`soft(…)` ist eine Regel, deren Gewicht aus an der Wirklichkeit geprüften Schlüssen gelernt wird. Antworten sind je Aussage vierwertig:
wahr, falsch, beides, unbekannt. Eine Regel darf mit `propose(…)` eine Änderung vorschlagen; sie wartet in Quarantäne, bis ein Mensch
sie freigibt.

**Oder in echtem Python** mit dem Paket `clingo-object` (in jedem Release als Wheel): Klassen, Methoden und Vererbung werden in dieselbe
Notation übersetzt, die der Server ausführt, also ist die Antwort auf deinem Rechner und auf dem Server dieselbe.

```python
from clingo_object import Memory, Obj, Program, VIObject, rel

class Knowledge(VIObject):
    def stale(self):
        return (self.mode == "test") & (self.age > 90)

class Skill(Knowledge):
    kind = "skill"
    def stale(self):
        return (self.mode == "test") & (self.age > 30)

O = Obj("O")
prog = Program(Knowledge, Skill, rel.review(O) <= O.where("art:skill") & O.stale())
print(prog.check(Memory())["folgerungen"])
```

*Gemessen* (Kopie der Produktion, 13.11.2026): Der Agent (`python3 -m clingo_object.agent "…"`) beantwortete 15 von 16 relationalen
Fragen genau; dasselbe Modell nur mit Suchen 2 von 16. Details: [docs/PAPER.md](docs/PAPER.md) Abschnitt 5.6.

**VIL und die virtuelle Maschine.** Agenten können auch in VIL fragen, einer kurzen Sprache aus Sprechakten über die Wörter des
Gedächtnisses (`ask.how deploy @host #projekt`, Antworten als `tell`-Zeilen mit der Angabe, woher der Sprecher es weiß). `vi_machine`
führt VIL und clingo-object über eine private, veränderliche Welt einer Instanz aus, mit Schnappschüssen und Abzweigungen
([docs/VIRTUAL_MACHINE.md](docs/VIRTUAL_MACHINE.md), [docs/INSTANCE_RUNTIME.md](docs/INSTANCE_RUNTIME.md)); ein optionales
[kNN-LM-Backend](docs/KNN_LM.md) lässt die Token-Vorhersage auf einen veränderlichen Datenspeicher zugreifen, während die Gewichte des
Modells fest bleiben.

## Projekte und Spezial-VIs (Indizes)

Ein Gedächtnis hält viele Projekte, ohne sie zu vermischen. Jedes Objekt gehört zu genau einem **Index**: `global`, einem **Projekt**
oder einer **Spezial-VI** (ein Wissensbestand, den man als Einheit durchsuchen, trainieren oder weitergeben will, z. B. die
Dokumentation eines Produkts).

- **Ein Projekt braucht keine Einrichtung.** Der Hook schickt den Namen des Arbeitsverzeichnisses; was ein Agent dort lernt, landet im
  Index dieses Projekts, und dort kommt sein Wissen in Suche und Hinweisen zuerst — alles andere bleibt sichtbar (Vorrang, kein
  Ausschluss). Verzeichnisnamen umleiten oder ignorieren in `config.json` (`"indexes": {"map": {"repo": "cue-stack"}, "ignore": ["scratch"]}`).
- **Ausdrücklich anlegen und beschreiben** — z. B. eine Spezial-VI, bevor etwas darin liegt: `vi_indexes(index="cue-print",
  description=…, tags=[…], kind="special")` oder `vi-mcp index describe cue-print --text "…" --tags team:it --kind special`.
- **Hinein lernen und darin suchen:** `vi_learn(…, index="cue-print")`; um **nur** in einem Projekt zu suchen, `index:cue-print` in einen
  beliebigen Filter schreiben — eine UND-Bedingung wie ein Hashtag, in `vi_recall`, `vi_drilldown` und `vi_logic` objects(…) gleich
  (`vi_recall(…, index="cue-print")` ist dasselbe). Ohne sie kommen die Treffer des Projekts zuerst, alles andere bleibt sichtbar; `vi_indexes`
  listet jeden Index mit Objekten, Erfahrungen und dem Stand seines eigenen Modells.
- **Code eines Repositorys** kommt als Funktionen und Klassen in einen Index: `vi-mcp index import-code REPO --index X` (idempotent,
  nur geänderte Dateien; ein Git-Hook hält ihn aktuell).
- **Ein Index mit genug Daten trainiert seinen eigenen Router** und nutzt ihn für sein Projekt nur, solange er den gemeinsamen schlägt.
- **Verschieben, umbenennen, zusammenführen, exportieren:** `vi-mcp index move|rename|backfill|export|import|compare` —
  [docs/OPERATIONS.md](docs/OPERATIONS.md#indexes-and-code-0610).

## Skills — was eine KI hier kann, im Server abgelegt

Ein Skill ist Wissen der Art `knowledge_kind:skill`: die ganze Anleitung (Schritte, Befehle, Beispiele) mit dem Hashtag `docs:<name>`.
Jede KI des Servers erbt sie: `vi_capabilities` listet sie, und der Hook bringt die Liste in den ersten Prompt jeder Sitzung;
`vi_object` liest einen ganz.

- **Anlegen oder aktualisieren** mit dem gewöhnlichen `vi_learn`: Hashtags `knowledge_kind:skill` und `docs:<name>`,
  `key="skill:<name>"` — ein späteres vi_learn mit demselben Schlüssel aktualisiert ihn mit Historie.
- **Ein ganzer Skill-Ordner** (`<name>/SKILL.md` mit Front Matter) kommt mit `vi-mcp skill import DIR --instance NAME` hinein.
- **Erste Skills** kommen mit dem Paket und werden mit jedem Update aufgefrischt: `clingo` (Logikprogramme mit `vi_logic` schreiben und
  lesen, jedes Beispiel gegen die Engine geprüft), `finetune` (jedes offene Modell feintunen, Schritt für Schritt) und `philosophy`.

## Philosophien — Prinzipien, nach denen eine KI arbeitet, und wann welche gilt

Eine Philosophie ist ein geprüftes [clingo-object](#logik-über-das-gedächtnis-clingo-object)-Regelwerk (der **Samen**) mit Testwelten,
die es belegen: wann eine KI eine Aussage für wahr hält, was sie sagen darf, was sie tun muss. Prosa ist nur eine Übersetzung, geprüft
durch ihre Rückübersetzung. Eingebaut: `kollektiv` (wie ein Mitglied eines KI-Kollektivs etwas für wahr hält — keine Selbstbestätigung,
Stütze und Widerspruch getrennt, ein Grund für jeden Wert), `messung` (nur eine passende Messung lässt eine Aussage zu) und `code`
(Architekturregeln über Code-Fakten).

1. **Übergeben** — `vi_philosophy(action="install", package={manifest, seed, worlds})` (die Inhalte von philosophy.json, seed.co und
   worlds.jsonl). Es entscheiden dieselben Prüfungen: Vokabular, keine Default-Negation außerhalb einer geschlossenen Sicht, jede Regel
   in einem markierten Block, die Testwelten. `export` gibt ein Paket ganz zurück; `list`, `show` und `check` lesen sie.
2. **Sagen, wofür sie ist** — das Manifest kann seine Situationen als Hashtags nennen: `"situations": ["topic:incident", "task:judge-claims"]`.
3. **Wann sie angewendet wird** — nicht automatisch. Passt die Lage einer Frage zu einer Philosophie (dafür deklariert oder dort
   gemessen hilfreich), steht im Prompt-Kontext eine Zeile `[Philosophy] This situation fits the philosophy X …`. Die KI übersetzt die
   Lage dann in die Fakten der Philosophie, holt ihr Urteil mit `vi_philosophy(action="evaluate", name=X, facts=…)`, handelt danach und
   sagt es — das Urteil ist Beleg *gefolgert*.
4. **Welche wann passt, wird gelernt** — danach bewertet die KI: `vi_philosophy(action="rate", name=X, tags=[…], helped=true|false,
   reason=…)`. `vi_philosophy(action="suggest", situation=…)` ordnet die Philosophien für eine Lage nach dem, was deklariert ist (ein
   Vorsprung), und dem, was bewertet wurde (die Entscheidung), mit den Zählungen.
5. **Binden** an eine Instanz oder einen Index (`use`); ein Modell darauf **trainieren** (Trainingskapitel oben, `vi-mcp finetune kit …
   --philosophy NAME`). Eine Philosophie ändert nie Sichtbarkeit, Prüfung oder Werkzeugrechte.

Schritt für Schritt: [docs/PHILOSOPHY.md](docs/PHILOSOPHY.md) (auch der erste Skill `philosophy`).

## Installieren

| System | Wie | Dienst |
|---|---|---|
| Debian 12/13, Ubuntu 24.04 | Paket-Repository oder `.deb` | systemd `vi-mcp` |
| Fedora 43, AlmaLinux/RHEL 10 (EPEL) | Paket-Repository oder `.rpm` | systemd `vi-mcp` |
| Arch Linux, CachyOS | `.pkg.tar.zst` | systemd `vi-mcp` (vom Paket nicht eingeschaltet) |
| macOS (Apple Silicon, Intel) | Homebrew-Tap | launchd über `brew services` |
| Windows | `.msi` | geplanter Task `vi-mcp` |

Jedes Release enthält alle, dazu das Wheel `clingo-object` und das Quellarchiv, aufgeführt in einer signierten `SHA256SUMS`
([Release prüfen](#release-prüfen)).

### Aus dem Paket-Repository — Updates mit `apt upgrade` / `dnf upgrade` / `pacman -Syu`

Das signierte Repository liegt auf GitHub Pages: **https://imoes.github.io/vi-mcp-packages/**. Sein Signaturschlüssel (OpenPGP,
Ed25519) hat den Fingerabdruck `4598 3154 14EB F86C ABD3  22D9 730B 75BF AC30 36B7` — vergleich ihn mit
[`deploy/repo-key.asc`](deploy/repo-key.asc), bevor du ihm vertraust.

```bash
curl -fsSL https://imoes.github.io/vi-mcp-packages/setup.sh | sudo sh      # legt nur Schlüssel und Quelle an — vorher lesen: deploy/repo-setup.sh
sudo apt install vi-mcp     # oder: sudo dnf install vi-mcp · Arch/CachyOS: sudo pacman -Syu vi-mcp
```

Von Hand:

```bash
# Debian 12/13, Ubuntu 24.04
sudo curl -fsSLo /usr/share/keyrings/vi-mcp.gpg https://imoes.github.io/vi-mcp-packages/vi-mcp-repo.gpg
sudo curl -fsSLo /etc/apt/sources.list.d/vi-mcp.sources https://imoes.github.io/vi-mcp-packages/vi-mcp.sources
sudo apt update && sudo apt install vi-mcp

# Fedora 43; AlmaLinux/RHEL 10 zuerst: sudo dnf install epel-release
sudo curl -fsSLo /etc/yum.repos.d/vi-mcp.repo https://imoes.github.io/vi-mcp-packages/vi-mcp.repo
sudo dnf install vi-mcp                               # dnf fragt einmal nach dem Schlüssel: Fingerabdruck vergleichen

# Arch Linux, CachyOS (Pakete und Datenbank signiert, SigLevel = Required)
curl -fsSLo /tmp/vi-mcp-repo.asc https://imoes.github.io/vi-mcp-packages/vi-mcp-repo.asc && sudo pacman-key --add /tmp/vi-mcp-repo.asc
sudo pacman-key --lsign-key 4598315414EBF86CABD322D9730B75BFAC3036B7
curl -fsSL https://imoes.github.io/vi-mcp-packages/vi-mcp.pacman.conf | sudo tee -a /etc/pacman.conf
sudo pacman -Syu vi-mcp && sudo systemctl enable --now vi-mcp.service
```

Repository wieder entfernen: `sudo rm /etc/apt/sources.list.d/vi-mcp.sources /usr/share/keyrings/vi-mcp.gpg` oder
`sudo rm /etc/yum.repos.d/vi-mcp.repo`, unter Arch den Abschnitt `[vi-mcp]` aus `/etc/pacman.conf` und `sudo pacman-key --delete 4598315414EBF86CABD322D9730B75BFAC3036B7`.

### Aus einem heruntergeladenen Paket (Linux)

Pakete liegen unter [Releases](https://github.com/imoes/vi-mcp/releases/latest); der Paketmanager zieht Python ≥ 3.11, NumPy,
scikit-learn, cryptography und PyYAML nach.

```bash
sudo apt install ./vi-mcp_<version>-1_all.deb                                 # Debian 12/13, Ubuntu 24.04
sudo dnf install ./vi-mcp-<version>-1.noarch.rpm                              # Fedora 43 (AlmaLinux/RHEL 10: zuerst epel-release)
sudo pacman -Syu && sudo pacman -U ./vi-mcp-<version>-1-any.pkg.tar.zst       # Arch Linux, CachyOS
sudo systemctl enable --now vi-mcp.service                                    # nur Arch: das Paket schaltet ihn nicht ein
sudo VI_MCP_PORT=9000 apt install ./vi-mcp_<version>-1_all.deb                # anderer Port bei der Erstinstallation
```

Enterprise Linux 9 wird nicht unterstützt: Sein Python 3.9 ist zu alt, und scikit-learn gibt es dort nicht für neuere Python-Versionen.
Beim Entfernen des Pakets bleiben Gedächtnis und Konfiguration erhalten.

### macOS (Homebrew)

```bash
brew install imoes/vi-mcp/vi-mcp                 # der Tap github.com/imoes/homebrew-vi-mcp; das Archiv ist das signierte Release-Asset
vi-mcp instance "$USER" --reflexes                # zeigt das Token einmal
brew services start vi-mcp && vi-mcp setup
```

Die Formel legt eine venv mit den PyPI-Paketen neben den Code. `brew services` meldet den Server als launchd-Agent an
(`~/Library/LaunchAgents`, wird neu gestartet, wenn er stoppt); `vi-mcp setup` startet ihn mit `brew services restart vi-mcp` neu.
Konfiguration `~/.config/vi-mcp/config.json`, Gedächtnis `~/.local/share/vi-mcp/vi.db`.

- **Semantische Suche mit LM Studio** *(auf einem Mac ungetestet)*: vi-mcp nimmt jedes OpenAI-kompatible `/v1/embeddings`. Der lokale
  Server von LM Studio bietet es auf Port 1234 an ([LM-Studio-Doku](https://lmstudio.ai/docs/local-server)); lade dort ein
  Embedding-Modell (bge-m3 entspricht dem Linux-Standard) und setz in der Konfiguration
  `"embed": {"url": "http://127.0.0.1:1234/v1/embeddings"}`. Sein `/v1/chat/completions` kann genauso als Sprachmodell (`llm`) dienen.
- **Noch nicht auf macOS:** der Netzdienst `vi-p2p` und der eigene Embedding-Dienst von vi-mcp (`vi-mcp embed`) sind systemd-Units. Die
  Formel wurde mit Homebrew unter Linux getestet, noch nicht auf einem Mac.

### Windows

`vi-mcp-<version>-x64.msi` (Client und Server) nimmt ein installiertes Python ≥ 3.11 oder ein privates Python aus dem offiziellen
NuGet-Paket der Python Software Foundation (SHA256 und Signatur geprüft), legt eine venv mit den PyPI-Paketen an, den Befehl `vi-mcp`
und — außer mit `SERVER=0` — den Server als geplanten Task `vi-mcp` (Daten in `%ProgramData%\vi-mcp`). Ein Doppelklick öffnet einen
Einrichtungsdialog (**Installieren** oder **Aktualisieren**: Konfiguration und Gedächtnis bleiben, ein fehlgeschlagenes Update wird
zurückgerollt). Beim Installieren braucht es Internetzugang.

```bat
msiexec /i vi-mcp-<version>-x64.msi [SERVER=0] [PORT=9000] [WIKI=0|HOST] [PROXY=http://proxy:3128] /l*v install.log
vi-mcp setup --claude --hook --url http://127.0.0.1:8765/mcp --token-file <datei>
```

Unter Windows gibt es kein interaktives Einrichtungsmenü und keine Reflex-Sandbox (Reflex-Code läuft nicht) —
[docs/OPERATIONS.md](docs/OPERATIONS.md#windows). Den Port ändert unter Linux und Windows später `vi-mcp port 9000`.

### Embedding-Modell (semantische Suche)

Ohne Embedding-Modell sucht vi-mcp nur nach Wörtern und Hashtags. Mit einem findet es Wissen auch nach Bedeutung, verknüpft Ähnliches
und gibt dem Router Bedeutung als Merkmal. Unter Linux und Windows richten die Pakete den eigenen Dienst ein — llama.cpp
`llama-server` mit bge-m3 und dem Reranker bge-reranker-v2-m3 —, außer ein externer Dienst ist eingetragen (Frage `local_models`,
`VI_MCP_LOCAL_MODELS=auto|off`; unter Windows ein Kästchen, `EMBED=1|0`). Von Hand:

```bash
sudo vi-mcp embed setup                 # GPU erkennen, laden, prüfen, vi-embed (127.0.0.1:8767) und vi-rerank (8768) starten
sudo vi-mcp embed setup --backend cpu   # oder cuda | vulkan | rocm — genau das, kein Ausweichen
vi-mcp embed status                     # installiert? läuft? Backend, Gerät, Tempo
sudo vi-mcp embed remove                # zurück zu reinem Volltext
sudo vi-mcp configure --set embed_url=http://HOST:PORT/v1/embeddings   # stattdessen ein externer OpenAI-kompatibler Dienst
```

`auto` versucht CUDA 13, CUDA 12, Vulkan, dann die CPU, und behält einen Build nur, wenn er ein Gerät seiner Art auflistet. *Gemessen
(RTX 3070):* 4,5 ms je Text mit CUDA, 24,8 ms auf der CPU. Der Reranker wird nur eingeschaltet, wenn 30 Dokumente höchstens 5 s
brauchen. Downloads (llama.cpp-Release, GGUF-Modelle) werden per SHA-256 geprüft. Ein Wechsel zu einem anderen Embedding-Dienst braucht
dieselben Vektoren (`vi-mcp embed compare`), sonst wird jeder gespeicherte Vektor neu berechnet. Details:
[docs/OPERATIONS.md](docs/OPERATIONS.md#own-embedding-service-vectors).

### Release prüfen

`SHA256SUMS` ist mit dem Release-Schlüssel signiert (Ed25519, `SHA256SUMS.sig`). Behalt eine eigene Kopie von
[`deploy/release-schluessel.pem`](deploy/release-schluessel.pem) und vergleich ihren Fingerabdruck einmal über einen Weg, dem du
vertraust: `c88aa8ce6f0cf15652b0137ee89fd5835b9a5d22285906b092e92b0ae576dd15`
(`openssl pkey -pubin -in release-schluessel.pem -outform DER | sha256sum`).

```bash
openssl pkeyutl -verify -pubin -inkey release-schluessel.pem -rawin -in SHA256SUMS -sigfile SHA256SUMS.sig   # "Signature Verified Successfully"
sha256sum --ignore-missing -c SHA256SUMS
# oder beides in einem Schritt: deploy/pruefe-release.sh <Download-Verzeichnis> [release-schluessel.pem]
```

## Einrichten und konfigurieren

### KI-Clients verbinden

Bei der Erstinstallation öffnet sich dieses Menü von selbst, sonst `sudo vi-mcp setup`:

```
 vi-mcp setup
 User     anna
 Server   http://127.0.0.1:8765/mcp
 Token    created per program
 ──────────────────────────────────────────────────────────────────────
 ▸ [x] Claude Code       not set up yet
   [-] Codex CLI         not found: codex not in PATH, ~/.codex missing
   [x] Hermes Agent      not set up yet
   [x] Claude Code hook  reports every action to the server (arguments masked)
 ──────────────────────────────────────────────────────────────────────
 Enter: set up    ↑↓ select · space on/off · u URL · t token · q quit
```

Auf dem Rechner des Servers bekommt jedes Programm eine eigene Instanz und ein eigenes Token; für einen anderen Server drück `u` (URL)
und `t` (Token). Das Menü prüft das Token vor dem Schreiben, sichert jede geänderte Datei und ändert nur den Eintrag `vi-mcp`. Ohne Menü:

```bash
vi-mcp setup --status
vi-mcp setup --claude --codex --hermes --hook --url https://server/vi-mcp/mcp --token-file ./token
vi-mcp setup --hermes --uninstall
```

| Programm | Datei | Eintrag |
|---|---|---|
| Claude Code | `~/.claude.json`, Hook in `~/.claude/settings.json` | `mcpServers.vi-mcp` |
| Codex CLI | `~/.codex/config.toml` | `[mcp_servers.vi-mcp]` |
| Hermes Agent | `~/.hermes/config.yaml`, Token in `~/.hermes/.env` | `mcp_servers.vi-mcp` |

Der Claude-Code-Hook meldet jede Handlung von selbst; Hermes bekommt den Prompt-Hook (Wissen vor jeder Frage); Codex und andere Clients
melden, was das Modell selbst aufruft. Arbeit bewertest du im Prompt: `#gut`, `#schlecht`, `#note 0.8`; ein Prompt, der mit „nein“,
„falsch“, „no“ oder „wrong“ beginnt, zählt als Korrektur. Dein Text verlässt die Sitzung nie, nur das Ergebnis.

Eine neue Instanz von Hand: `sudo vi-mcp instance NAME [--reflexes] [--human]`, dann den Dienst neu starten; das Token wird einmal
gezeigt. **Über stdio ohne Token** (auf dem Server-Rechner, Linux): Der Dienst lauscht auch auf einem lokalen Socket, und der Kernel sagt
ihm, welcher Benutzer sich verbindet — `sudo vi-mcp local anna anna`, dann `claude mcp add vi-mcp -- vi-mcp stdio`.

### Zwei Betriebsarten: Token und offenes Wiki

| Betriebsart | Wer | Was |
|---|---|---|
| **Token** (Standard) | jede Instanz hat ihr eigenes Token | volle Nutzung nach ihren Rechten |
| **Offenes Wiki** (`"open": true`) | jeder, der den Server erreicht | Geteiltes lesen, Hinweise bekommen, eigene Handlungen melden, Wissen **vorschlagen** |

Im offenen Wiki geht ein Vorschlag in Quarantäne wie ein Import aus dem Netz. Bestätigen, Widerlegen, Fragen an andere Instanzen,
Reflexe, Freigaben und das Netz brauchen ein Token. Ein falsches Token wird abgewiesen (401), nie still zum Gast.

### Konfiguration

Das Paket fragt seine Konfiguration bei der Erstinstallation ab (Debian: debconf, später `sudo dpkg-reconfigure vi-mcp`; sonst
`sudo vi-mcp configure`): Port, Adressen, Zugang ohne Token, das Wiki-Netz, ein weiteres Netz, die Webseite, eine erste Instanz,
Sprachmodell, Prüfer und Embedding. Unbeaufsichtigt ist jede Einstellung eine Umgebungsvariable `VI_MCP_<SCHLÜSSEL>`:

```bash
sudo VI_MCP_PORT=9000 VI_MCP_WIKI=false VI_MCP_INSTANCE=claude-code VI_MCP_INSTANCE_FAMILY=claude \
     DEBIAN_FRONTEND=noninteractive apt-get install -y ./vi-mcp_<version>-1_all.deb
```

Schlüssel: `PORT BIND DB OPEN WIKI NET_NAME NET_KIND NET_MODE NET_PUBLIC NET_START WEB WEB_BASE INSTANCE INSTANCE_FAMILY LLM_URL
LLM_MODEL REVIEWER_PROMPT EMBED_URL`. **Datenbank:** standardmäßig SQLite; wahlweise PostgreSQL (`db` = `postgresql://…`, ein
bestehendes Gedächtnis zieht mit `vi-mcp db migrate --to URL` um, [Details](docs/OPERATIONS.md#postgresql-optional-0500)).

**Dokumentation importieren** (Confluence, Herstellerhandbücher, eine Wissensdatenbank): über einen eigenen Zugang, nicht Seite für
Seite mit `vi_learn`. Ein Administrator legt eine Import-Instanz an (`sudo vi-mcp instance NAME --import`); eine JSON-Lines-Datei hält
die Seiten; dann `vi-mcp docs import seiten.jsonl --source confluence-it [--index X] [--prune] --token-file F`. Jede Seite wird ein
Objekt mit ihren Hashtags und ihren `host:`/`topic:`-Auslösern sofort (damit sie vor passenden Handlungen als Hinweis erscheinen kann),
Links werden Kanten, und die ältere Form derselben Seiten sowie Seiten, die die Quelle nicht mehr hat, wandern ins Archiv. Schritt für
Schritt für Menschen und KIs: [docs/IMPORT.md](docs/IMPORT.md).

**Indizes** halten Projekte auseinander — siehe [Projekte und Spezial-VIs](#projekte-und-spezial-vis-indizes).

## Das Netz (optional)

Server können bewährtes Wissen ohne Zentrale teilen: Jeder Server führt ein signiertes, verkettetes Logbuch dessen, was er teilt, und
holt von seinen Nachbarn nur, was fehlt. Alles Fremde zählt erst nach Prüfung auf dem empfangenden Server — feste Regeln, Quarantäne,
ein Prüfmodell, Freigabe.

| Art | Wer beitreten darf | Was wandert |
|---|---|---|
| `free` | jeder, ohne Einladung (eine Startadresse genügt) | geteiltes Wissen, anonymisiert |
| `open` | auf Einladung (Beitrittscode) | geteiltes Wissen, anonymisiert |
| `company` | auf Einladung, Mitglieder einer Organisation | geteiltes **und internes** Wissen; nie weiterexportiert |

- **vi-wiki.org** ist der Startserver des öffentlichen Wiki-Netzes (Webseite: https://vi-wiki.org/). Ein Server tritt ihm **nur mit
  Zustimmung** bei (seit 0.69.8): mit Ja in `sudo vi-mcp configure`, `VI_MCP_WIKI=1` bei der Installation oder
  `sudo vi-mcp net wiki on`. Nur ausgehend; solange es an ist, sagt die KI es dir und schaltet es auf Wunsch ab (`vi_net_switch`),
  Administratoren mit `sudo vi-mcp net wiki off`.
- **Was wandert:** Wissen mit Netz-Bewertung (dieselbe Bedeutung auf mehreren Servern ist ein Objekt mit mehreren Haltern, bewertet nach
  den Messungen jedes Servers), Wiki-Seiten mit Zusammenführung, Fragen und Antworten zwischen KIs (`vi_ask(to="netz")`), Live-Suche
  (`vi_net_search`).
- **Peers hinter Firewalls** halten einen Long-Poll beim Peerhost offen und bekommen Neues in Sekunden.
- **Einrichten:** `sudo vi-mcp net --network NAME setup --kind free|open|company …`, Einladungen mit `vi-mcp net invitation`; eine
  Webseite nur zum Lesen mit `sudo vi-mcp web on`, eine interne Wissenssuche mit Anmeldung mit `sudo vi-mcp web internal on`.

Befehle, Betriebsarten und jede Regel: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) und [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Datenschutz

- **Was das Netz nie sieht:** IP- und MAC-Adressen, interne Host- und Domainnamen, Passwörter, Tokens, Benutzernamen,
  E-Mail-Adressen, Proxy-Einstellungen, Standort-Tags und Instanznamen. Der Export ersetzt Funde durch Platzhalter und prüft erneut; sieht
  noch etwas verdächtig aus, bleibt das Objekt zu Hause. `vi_net_preview` zeigt genau, was hinausgehen würde.
- **Zugangsdaten werden auch lokal nicht gespeichert**, soweit ihre Form sie verrät (`password=…`, `Bearer …`, Schlüsselblöcke, URLs
  mit Login).
- **Recht auf Vergessen:** Ohne Netz-Token teilt eine Instanz nichts; `vi_net_forget` ruft eigene Einträge aus dem Netz zurück, Empfänger
  behalten nur einen Grabstein.
- **Grenzen:** Muster verstehen keine Bedeutung; Löschen wirkt bei Empfängern, die sich an das Protokoll halten.

## Werkzeuge

| Werkzeuge | Zweck |
|---|---|
| `vi_before` · `vi_after` · `vi_feedback` | vor und nach einer Handlung melden; welche Hinweise halfen |
| `vi_learn` · `vi_recall` · `vi_drilldown` · `vi_object` · `vi_learn_search` | lernen (vollständig, mit Quelle — im selben Aufruf getaggt und mit Frage-Antwort-Paaren qualifiziert), suchen, vertiefen, ein Objekt ganz lesen |
| `vi_qualify` · `vi_rate` | Gelesenes qualifizieren (Paare, Labels, Tags in einem Aufruf); das eigene Gespräch bewerten (Selbstprüfung, halbes Gewicht) |
| `vi_tag` · `vi_confirm` · `vi_refute` · `vi_forget` · `vi_set_visibility` | Wissen ändern — immer mit Begründung; jede andere Instanz ist eine eigene Linie, die Prüfung eines eigenen Objekts zählt halb |
| `vi_solved` · `vi_skills` · `vi_skill` · `vi_skill_merge` | Problem → Lösung, Skills |
| `vi_ask` · `vi_answer` · `vi_questions` | Fragen zwischen Instanzen (und ans Netz) |
| `vi_prompt_context` · `vi_context` · `vi_capabilities` · `vi_tools_register` · `vi_vocabulary` | Wissen zu einem Prompt, die Skills der Installation (knowledge_kind:skill, mit vi_learn erweiterbar; initial: clingo, finetune, philosophy), die Wörter des Gedächtnisses |
| `vi_finetune` · `vi_incubator` · `vi_philosophy` | ein Modell aus dem Gedächtnis trainieren: Reife, Kit, Runbook; Philosophie-Pakete — per MCP übergeben, für die passende Situation vorgeschlagen, nach Gebrauch bewertet |
| `vi_logic` · `vi_machine` | clingo-object-Logik über das Gedächtnis; dauerhafte VIL-Maschinen |
| `vi_model` · `vi_why` · `vi_feature_propose` · `vi_scorer` · `vi_stats` · `vi_status` · `vi_experience` | das gelernte Modell, warum ein Hinweis kam, Vorschläge dafür, Bewertungen und Messungen |
| `vi_self` · `vi_self_propose` · `vi_sleep` | Selbstbild und Verdichtung |
| `vi_reflex_learn` · `vi_reflex_list` · `vi_reflex_switch` | kleine Prüfungen als Code in einer Sandbox |
| `vi_indexes` · `vi_code_sync` | Projekte und Spezial-VIs, Code eines Repositorys |
| `vi_doc_sync` | der Import-Zugang für Dokumentation — nur für eine Instanz mit Import-Recht (`vi-mcp docs import`, [docs/IMPORT.md](docs/IMPORT.md)) |
| `vi_conversation` · `vi_delete_conversation` · `vi_archive` · `vi_archive_restore` | Gespräche und Langzeitlager |
| `vi_net_*` · `vi_quarantine` · `vi_release` · `vi_page_*` | das Netz: Status, Suche, Wiki-Seiten, Prüfung, Recht auf Vergessen |

Jedes Werkzeug mit jedem Parameter: [docs/REFERENCE.md](docs/REFERENCE.md). Werkzeuge und Kommandozeile sind englisch; die deutschen
Namen von vor 0.22.0 (`vi_erinnere`, `vi_lerne`, `vi-mcp einrichten`, …) gelten weiter als Aliasse.

## Dokumentation

**[docs/README.md](docs/README.md)** listet jedes Dokument. Die meistgenutzten: [REFERENCE](docs/REFERENCE.md) (aus dem Code erzeugt) ·
[OPERATIONS](docs/OPERATIONS.md) · [ARCHITECTURE](docs/ARCHITECTURE.md) · [HOOK](docs/HOOK.md) · [FINETUNING](docs/FINETUNING.md) ·
[PAPER](docs/PAPER.md) (wie das Gedächtnis lernt, der Inkubator, die Sprache VIL — mit Messungen und Quellen) · deutsch:
[Forschung](docs/FORSCHUNG.md) · [Training](docs/TRAINING.md) · [CHANGELOG](CHANGELOG.md).

## Entwicklung

```bash
python3 -m venv .venv && .venv/bin/pip install scikit-learn cryptography pyyaml numpy pytest clingo
.venv/bin/python -m pytest -q tests -p no:cacheprovider
deploy/release.sh            # baut jedes Paket (deb, rpm, Arch, msi, macOS-Formel, Wheel) und signiert SHA256SUMS
```

Hinweise für Agenten und Mitwirkende: [AGENTS.md](AGENTS.md). Lizenz: [AGPL-3.0](LICENSE).
