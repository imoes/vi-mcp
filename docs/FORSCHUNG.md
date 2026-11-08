# Wie Menschen sich erinnern — und was vi-mcp daraus übernehmen kann

**Frage des Auftraggebers:** „Wie memorieren Menschen und geben Gelerntes wieder, und wie setzt man diese
neurologische Strategie in ein KI-Modell um, sodass wir eine virtuelle Persönlichkeit bekommen?“

**Stand:** 08.11.2026. **Gegenstand:** vi-mcp 0.1.1 (`dem Repository`). Das Repo wurde nur
gelesen, nicht geändert.

## Belegstufen (gilt für jede Aussage unten)

| Kürzel | Bedeutung |
|---|---|
| **[V]** | Volltext gelesen; die Stelle ist angegeben (Abschnitt bzw. Zeile im extrahierten PDF-Text) |
| **[A]** | Abstract gelesen (Verlag oder arXiv). **[A-tldr]** = nur die maschinell erzeugte TLDR von Semantic Scholar, also eine Sekundärquelle |
| **[T]** | Nur die bibliographischen Angaben geprüft (Titel, Zeitschrift, Band, Seiten über die Crossref-API, 08.11.2026). Die inhaltliche Wiedergabe stammt aus Erinnerung und gilt als **Hypothese/unbelegt** |
| **[E]** | Aus Erinnerung, nicht nachgeschlagen: **Hypothese/unbelegt** |
| **[C]** | Code von vi-mcp, als `Datei:Zeile` |
| **[S]** | Sekundärquelle (Übersichtsartikel oder Website über die Primärquelle) |

So wurde geprüft: Die DOIs liefen über `https://api.crossref.org/works/<doi>` (alle unten genannten wurden
gefunden). Die Abstracts kamen über `https://api.semanticscholar.org/graph/v1/paper/batch`. Die arXiv-Paper wurden
als PDF geladen (`https://arxiv.org/pdf/<id>`), mit `pdftotext` umgewandelt und durchsucht. Die Venues stammen aus
den Metadaten der arXiv-API.

---

## A — Wie menschliches Gedächtnis funktioniert

### A1 Einspeichern (Enkodierung)

- **Verarbeitungstiefe:** Wie gut etwas behalten wird, hängt von der Tiefe der Verarbeitung ab, nicht von einem
  festen Speicherort. Bedeutungsvolles Verarbeiten hält besser als oberflächliches.
  Craik & Lockhart 1972, *J. Verbal Learning & Verbal Behavior* 11:671–684,
  doi:10.1016/S0022-5371(72)80001-X **[A-tldr]**. Dass Elaboration (Verknüpfen mit Vorwissen) den Effekt trägt, ist
  **[E]**.
- **Ereignisgrenzen:** Der Mensch zerlegt den Erlebnisstrom an Stellen, an denen sich die Vorhersage ändert, in
  Ereignisse. Zacks et al. 2007, *Psychol. Bull.* 133:273–293, doi:10.1037/0033-2909.133.2.273 **[T]**.
  EM-LLM überträgt das auf LLMs: Token werden über „Bayesian surprise“ plus graphentheoretische
  Grenzverfeinerung zu Episoden gruppiert. Fountas et al., arXiv 2407.09450, ICLR 2025 **[V]** (Abstract, Z. 30–31).

### A2 Arbeitsgedächtnis

- Die Kapazität liegt bei etwa **3–5 Chunks**. Millers „7 ± 2“ war eher eine rhetorische Schätzung.
  Cowan 2001, *Behav. Brain Sci.* 24:87–114, doi:10.1017/S0140525X01003922 **[A]**.
  Miller 1956, *Psychol. Rev.* 63:81–97, doi:10.1037/h0043158 **[T]**.
- Baddeleys „episodischer Puffer“ verbindet das Arbeitsgedächtnis mit dem Langzeitgedächtnis.
  Baddeley 2000, *TiCS* 4:417–423, doi:10.1016/S1364-6613(00)01538-2 **[T]**.
- Experten umgehen die Grenze über abrufbare Strukturen im Langzeitgedächtnis („long-term working memory“).
  Ericsson & Kintsch 1995, *Psychol. Rev.* 102:211–245, doi:10.1037/0033-295X.102.2.211 **[T]**.

### A3 Gedächtnissysteme: episodisch, semantisch, prozedural

- **Episodisch** heißt: erlebte Ereignisse mit Ort und Zeit. **Semantisch** heißt: kontextfreies Wissen.
  Tulving 2002, *Annu. Rev. Psychol.* 53:1–25, doi:10.1146/annurev.psych.53.100901.135114 **[T]**.
- **Deklarativ** (episodisch und semantisch, hippocampusabhängig) steht neben **nichtdeklarativ** (prozedural,
  Gewohnheiten, Priming). Squire 2004, *Neurobiol. Learn. Mem.* 82:171–177, doi:10.1016/j.nlm.2004.06.005 **[T]**.

### A4 Konsolidierung, Replay und Schlaf

- **Systemkonsolidierung:** Frische Erinnerungen hängen am Hippocampus. Mit der Zeit werden sie im Neokortex
  unabhängiger. Frankland & Bontempi 2005, *Nat. Rev. Neurosci.* 6:119–130, doi:10.1038/nrn1607 **[T]**.
  Moscovitch et al. 2016, *Annu. Rev. Psychol.* 67:105–134, doi:10.1146/annurev-psych-113011-143733 **[T]**
  (Transformation statt bloßer Verlagerung).
- **Replay:** Ensembles im Hippocampus, die tagsüber gemeinsam feuerten, werden im Schlaf erneut aktiviert.
  Wilson & McNaughton 1994, *Science* 265:676–679, doi:10.1126/science.8036517 **[T]**.
  Kausaler Nachweis: Wer die Sharp-Wave-Ripples unterdrückt, verschlechtert das räumliche Gedächtnis.
  Girardeau et al. 2009, *Nat. Neurosci.* 12:1222–1223, doi:10.1038/nn.2384 **[T]**.
- **Schlaf sortiert aus („Triage“):** Er wählt aus, was behalten wird, integriert es in bestehende Netze und
  **destilliert übergreifende Regeln**. Stickgold & Walker 2013, *Nat. Neurosci.* 16:139–145,
  doi:10.1038/nn.3303 **[A]**. Übersichten: Diekelmann & Born 2010, *Nat. Rev. Neurosci.* 11:114–126,
  doi:10.1038/nrn2762 **[A-tldr]**; Rasch & Born 2013, *Physiol. Rev.* 93:681–766,
  doi:10.1152/physrev.00032.2012 **[T]**.
- **Was künftig gebraucht wird, wird bevorzugt konsolidiert:** Schlaf verbesserte den späteren Abruf nur, wenn die
  Probanden wussten, dass ein Test folgt. Wilhelm et al. 2011, *J. Neurosci.* 31:1563–1569,
  doi:10.1523/JNEUROSCI.3575-10.2011 **[A]**.
- **Priorisiertes Replay:** Erinnerungen werden nach ihrem **Nutzen für künftige Entscheidungen** abgerufen. Das
  wägt ab zwischen „bald nötig“ und „neue Information nach hinten propagieren“. Mattar & Daw 2018,
  *Nat. Neurosci.* 21:1609–1617, doi:10.1038/s41593-018-0232-z **[A]**.

### A5 Komplementäre Lernsysteme (CLS)

- **McClelland, McNaughton & O'Reilly 1995**, *Psychol. Rev.* 102:419–457, doi:10.1037/0033-295X.102.3.419
  **[A-tldr]**: Der Hippocampus speichert schnell. Wird eine Spur wieder eingespielt, ändert sich der Neokortex jedes
  Mal ein wenig. Fernes Gedächtnis entsteht aus diesen akkumulierten Änderungen. Der Grund für zwei Systeme ist
  katastrophale Interferenz: Ein langsam lernendes verteiltes Netz überschreibt Altes, wenn es Neues nicht
  *verschränkt (interleaved)* mit Altem lernt. Diese Begründung ist **[E]**. Das Phänomen selbst belegen
  McCloskey & Cohen 1989, *Psychol. Learn. Motiv.* 24:109–165, doi:10.1016/S0079-7421(08)60536-8 **[T]**, und
  French 1999, *TiCS* 3:128–135, doi:10.1016/S1364-6613(99)01294-2 **[T]**.
- **Kumaran, Hassabis & McClelland 2016**, *TiCS* 20:512–534, doi:10.1016/j.tics.2016.05.004 **[A-tldr]**: Das
  wiederholte Aktivieren hippocampaler Spuren erlaubt bereits Generalisierung. Neokortikales Lernen kann **schnell**
  sein, **wenn die neue Information zu bekannter Struktur passt**.
- **Indexing-Theorie:** Der Hippocampus speichert **Zeiger (Indizes)** auf neokortikale Muster, nicht die Inhalte
  selbst. Teyler & DiScenna 1986, *Behav. Neurosci.* 100:147–154, doi:10.1037/0735-7044.100.2.147 **[T]**.
  HippoRAG baut genau darauf auf **[V]** (arXiv 2405.14831, Abschnitt 2 „The Hippocampal Memory Indexing Theory“).

### A6 Schemata

- Gibt es bereits ein passendes Schema, kann Systemkonsolidierung **sehr schnell** gehen. Tse et al. 2007,
  *Science* 316:76–82, doi:10.1126/science.1135935 **[A-tldr]**.
- Schema-Kongruenz und Neuheit stärken das Gedächtnis beide, über verschiedene Hirnpfade (mPFC bzw. mediale
  Temporallappen). van Kesteren et al. 2012, *TINS* 35:211–219, doi:10.1016/j.tins.2012.02.001 **[A-tldr]**.

### A7 Vorhersagefehler und Überraschung als Lernsignal

- Dopaminneurone kodieren den **Belohnungs-Vorhersagefehler**. Schultz, Dayan & Montague 1997, *Science*
  275:1593–1599, doi:10.1126/science.275.5306.1593 **[T]**.
- Ein Vorhersagefehler verbessert auch das **einmalige deklarative Lernen**, in fünf Experimenten. Greve et al. 2017,
  *J. Mem. Lang.* 94:149–165, doi:10.1016/j.jml.2016.11.001 **[A]**.
- Ein Vorhersagefehler macht Erinnerungen **veränderbar** (Rekonsolidierung). Sinclair & Barense 2019, *TINS*
  42:727–739, doi:10.1016/j.tins.2019.08.007 **[A]**.

### A8 Rekonsolidierung

- Nach dem Abruf ist eine Erinnerung vorübergehend **labil**. Bis sie sich wieder stabilisiert, kann sie
  abgeschwächt, verstärkt oder mit neuer Information aktualisiert werden. Nader, Schafe & LeDoux 2000, *Nature*
  406:722–726, doi:10.1038/35021052 **[T]**. Lee, Nader & Schiller 2017, *TiCS* 21:531–545,
  doi:10.1016/j.tics.2017.04.006 **[A]**. Nader & Hardt 2009, *Nat. Rev. Neurosci.* 10:224–234,
  doi:10.1038/nrn2590 **[T]**.

### A9 Vergessen

- **Ebbinghaus 1885:** Ersparnismethode und Vergessenskurve. Primärtext (engl. Übers. 1913):
  https://psychclassics.yorku.ca/Ebbinghaus/index.htm. Die Kurve wurde repliziert: Murre & Dros 2015, *PLOS ONE*
  10:e0120644, doi:10.1371/journal.pone.0120644 **[T]**.
- **Form der Kurve:** Vergessen folgt eher einer **Potenzfunktion** als einer Exponentialfunktion. Wixted & Ebbesen
  1991, *Psychol. Sci.* 2:409–415, doi:10.1111/j.1467-9280.1991.tb00175.x **[T]**. Rubin & Wenzel 1996 haben 100
  Jahre Behaltensdaten ausgewertet: *Psychol. Rev.* 103:734–760, doi:10.1037/0033-295X.103.4.734 **[T]**.
  Anderson & Schooler 1991 zeigten, dass Häufigkeit und Recency in der **Umwelt** dieselben Potenzgesetze haben.
  Gedächtnis ist demnach eine rationale Vorhersage, was gebraucht wird. *Psychol. Sci.* 2:396–408,
  doi:10.1111/j.1467-9280.1991.tb00174.x **[T]**.
- **Verteiltes Lernen (Spacing):** Der optimale Abstand zwischen Wiederholungen wächst mit dem Behaltensintervall.
  Cepeda et al. 2006, *Psychol. Bull.* 132:354–380, doi:10.1037/0033-2909.132.3.354 **[A-tldr]**.
  Ein Mechanismus dafür: Jede Übung gibt einen Stärkezuwachs, der **als Potenzfunktion zerfällt**. Die
  **Zerfallsrate hängt von der Aktivierung zum Zeitpunkt der Übung ab**. Wer also bei hoher Aktivierung übt
  (massiert), gewinnt wenig, und daraus folgt der Spacing-Effekt. Pavlik & Anderson 2005, *Cogn. Sci.* 29:559–586,
  doi:10.1207/s15516709cog0000_14 **[A]**. Die ACT-R-Formel für die Basisaktivierung
  `B = ln Σ_j t_j^(−d)`, Standard `d = 0,5`, ist **[E]**. Zum Nachprüfen: Anderson et al. 2004, *Psychol. Rev.*
  111:1036–1060, doi:10.1037/0033-295X.111.4.1036 **[T]**.
- **Abrufinduziertes Vergessen:** Wer einige Inhalte abruft, schwächt konkurrierende Inhalte unter demselben
  Hinweisreiz. Anderson, Bjork & Bjork 1994, *JEP:LMC* 20:1063–1087, doi:10.1037/0278-7393.20.5.1063 **[A-tldr]**.
- **Vergessen ist eine Funktion, kein Defekt:** Vergänglichkeit macht flexibler, weil veraltete Information weniger
  Einfluss hat, und sie verhindert Überanpassung an Einzelereignisse, was die Generalisierung fördert. Richards &
  Frankland 2017, *Neuron* 94:1071–1084, doi:10.1016/j.neuron.2017.04.037 **[A-tldr]**.

### A10 Abruf

- **Enkodierungsspezifität:** Ein Hinweisreiz hilft nur, wenn er beim Einspeichern mitkodiert wurde. Tulving &
  Thomson 1973, *Psychol. Rev.* 80:352–373, doi:10.1037/h0020071 **[T]**.
  **Kontextabhängigkeit:** Taucher erinnerten besser im selben Medium (an Land oder unter Wasser), in dem sie gelernt
  hatten. Godden & Baddeley 1975, *Br. J. Psychol.* 66:325–331, doi:10.1111/j.2044-8295.1975.tb01468.x **[T]**.
- **Testing-Effekt:** Abrufen festigt stärker als erneutes Lernen. Bei kurzem Intervall liegt Wiederlesen vorn, nach
  Tagen das Abrufen. Roediger & Karpicke 2006, *Psychol. Sci.* 17:249–255, doi:10.1111/j.1467-9280.2006.01693.x
  **[T]**. Karpicke & Roediger 2008, *Science* 319:966–968, doi:10.1126/science.1152408 **[T]**. Die Detailzahlen
  sind **[E]**.
- **Abruf ist Rekonstruktion:** Erinnern baut das Ereignis neu auf und ist dadurch fehleranfällig. Schacter 1999,
  *Am. Psychol.* 54:182–203, doi:10.1037/0003-066X.54.3.182 **[T]**. Schacter & Addis 2007, *Phil. Trans. R. Soc. B*
  362:773–786, doi:10.1098/rstb.2007.2087 **[T]**.

### A11 Emotionale Salienz

- Die Amygdala vermittelt, dass emotional bedeutsame Erlebnisse besser konsolidiert werden, über Stresshormone und
  Neuromodulatoren. McGaugh 2004, *Annu. Rev. Neurosci.* 27:1–28, doi:10.1146/annurev.neuro.27.070203.144157
  **[A-tldr]**.
- Emotionale Episoden werden **langsamer vergessen**. Das betrifft vor allem die Bindung zwischen Inhalt und Emotion,
  weniger den Kontext. Yonelinas & Ritchey 2015, *TiCS* 19:259–267, doi:10.1016/j.tics.2015.02.009 **[A]**.

### A12 Autobiographisches Gedächtnis, Selbst und Persönlichkeit

- **Self-Memory System (SMS):** Conway & Pleydell-Pearce 2000, *Psychol. Rev.* 107:261–288,
  doi:10.1037/0033-295X.107.2.261 **[T]**. Conway 2005, *J. Mem. Lang.* 53:594–628, doi:10.1016/j.jml.2005.08.005
  **[T]**. Der Kern laut Sekundärquelle **[S]** (Übersicht in *Front. Psychol.* 2017, doi:10.3389/fpsyg.2017.02250,
  https://pmc.ncbi.nlm.nih.gov/articles/PMC5744072):
  - Das **Working Self** ist eine Hierarchie aktueller Ziele. Es steuert, welche Erinnerungen zugänglich sind, und
    hält das Selbst kohärent.
  - Die **autobiographische Wissensbasis** ist geschichtet: ereignisspezifisches Wissen, dann allgemeine Ereignisse,
    dann Lebensabschnitte, darüber abstraktes Selbstkonzept.
  - Zwischen **Korrespondenz** (Treue zum Erlebten) und **Kohärenz** (Stimmigkeit mit Zielen und Selbstbild)
    besteht eine Spannung.
- Menschen konstruieren ihre Vergangenheit so, dass das gegenwärtige Selbst **kohärent und eher günstig** erscheint.
  Wilson & Ross 2003, *Memory* 11:137–149, doi:10.1080/741938210 **[A-tldr]**. Für ein künstliches Selbst ist das ein
  Risiko (siehe D).
- **Narrative Identität:** Identität ist eine fortlaufend fortgeschriebene Lebensgeschichte. McAdams 2001,
  *Rev. Gen. Psychol.* 5:100–122, doi:10.1037/1089-2680.5.2.100 **[T]**.
- **Identität ist nicht dasselbe wie episodisches Gedächtnis:** Ein Amnesiepatient behielt zutreffendes Wissen über
  die eigenen Eigenschaften. Klein, Loftus & Kihlstrom 1996, *JEP:General* 125:250–260,
  doi:10.1037/0096-3445.125.3.250 **[T]**. Klein & Nichols 2012, *Mind* 121:677–702, doi:10.1093/mind/fzs080 **[T]**.
  Als **Kern der Identität** gelten **moralische Eigenschaften (Werte)**, nicht Erinnerungen oder Fähigkeiten.
  Strohminger & Nichols 2014, *Cognition* 131:159–171, doi:10.1016/j.cognition.2013.12.005 **[A-tldr]**.
- **Persönlichkeit ist stabil, aber nicht starr:** Die Rangordnungs-Konsistenz von Eigenschaften nimmt mit dem Alter
  zu und mit dem Zeitabstand ab. Roberts & DelVecchio 2000, *Psychol. Bull.* 126:3–25,
  doi:10.1037/0033-2909.126.1.3 **[A-tldr]**.

**Folgerung für A (Synthese, keine Einzelquelle):** Eine Persönlichkeit entsteht aus drei Bausteinen:
1. einem **schnellen episodischen Speicher** mit Kontext und Zeit;
2. einem **langsamen, abstrahierenden Wissensspeicher**, der offline (im Schlaf) **ausgewählt und verschränkt**
   gespeist wird;
3. einem **Working Self** aus Werten und Zielen, das Abruf und Bewertung steuert und sich nur langsam ändert.

Wichtig bleibt dabei: Was gebraucht, überraschend oder emotional bedeutsam ist, bleibt. Der Rest verblasst, und das
ist gewollt.

---

## B — Umsetzungen in KI-Systemen

### B1 Generative Agents (Park et al. 2023)

Quelle: arXiv 2304.03442v2, UIST '23, doi:10.1145/3586183.3606763. **[V]**, Volltext geprüft.

- **Recency:** „exponential decay function over the number of sandbox game hours since the memory was last
  retrieved. Our decay factor is 0.995.“ (Abschnitt 4.1)
- **Zeitmaßstab:** „one second real time is one minute game time“ (Anhang A). 0,995 gilt also **je Spielstunde**,
  das entspricht etwa **einer Minute Echtzeit** im Lauf des Papers.
- **Importance:** Das LLM bewertet die „poignancy“ auf einer Skala von **1–10**, **einmal beim Anlegen**
  (Abschnitt 4.1, Prompt im Text).
- **Relevance:** Kosinus-Ähnlichkeit der Embeddings zwischen Erinnerung und Anfrage.
- **Score:** Alle drei Komponenten werden **per Min-Max auf [0,1] normiert** und mit α = 1 summiert.
- **Reflection:** Sie wird ausgelöst, wenn die **Summe der Importance-Werte der jüngsten Ereignisse 150
  übersteigt**. In der Praxis geschah das 2–3-mal pro Spieltag. Ablauf:
  1. Aus den **100 jüngsten Einträgen** erzeugt das Modell die „3 most salient high-level questions“.
  2. Zu jeder Frage läuft ein Abruf.
  3. Daraus werden **5 Erkenntnisse mit Belegverweisen** („because of 1, 5, 3“) abgeleitet.
  4. Sie werden als Reflexion gespeichert, mit **Zeigern auf die Belege**.

  Reflexionen über Reflexionen ergeben einen Baum (Abschnitt 4.2).
- **Identität:** Ein „Agent's Summary Description“ wird **regelmäßig neu synthetisiert und zwischengespeichert**.
  Er entsteht aus drei Abfragen: „core characteristics“, „current daily occupation“ und „feeling about his recent
  progress in life“, dazu Name, Alter und Eigenschaften (Anhang A).
- **Bekannter Fehler:** Die Agenten **schmücken Erinnerungen aus**, auch mit Weltwissen aus dem Modell (Abschnitt
  6.5.2).

**Abgleich mit vi-mcp:**
- `VERFALL_JE_H = 0.995` (`gedaechtnis.py:35`) **stimmt als Zahl** mit dem Paper überein. **Die Einheit stimmt
  nicht:** vi-mcp wendet den Faktor je **Echtzeit-Stunde** an. Die Halbwertszeit ist ln 0,5 / ln 0,995 ≈ **138 h ≈
  5,8 Tage**. Im Paper sind 138 Spielstunden etwa 138 Minuten Echtzeit.
- Die Notiz in `docs/ARCHITEKTUR.md:76` („Annahme, nicht gegen das Paper geprüft“) kann damit präzisiert werden:
  Der Faktor ist belegt, die Zeiteinheit ist eine eigene Wahl.
- vi-mcp **normiert nicht per Min-Max**. Ohne Freiwörter ist `relevanz = 1` für alle Treffer
  (`gedaechtnis.py:330`), dann entscheiden nur Aktualität und Wichtigkeit.
- Die Wichtigkeit ist fest kodiert (`intuition.py:148`: Fehler = 2, sonst 0) bzw. manuell gesetzt (`vi_lerne`). Sie
  wird **nicht** vom Modell bewertet.

### B2 MemGPT / Letta

Quelle: Packer et al., arXiv 2310.08560 **[V]**.

- Der Kontext ist in drei Teile gegliedert:
  - **System-Instruktionen** (nur lesbar);
  - **Working Context**: ein fester Lese-/Schreibblock für „key facts, preferences, … about the user and the persona
    the agent is adopting“, nur über Funktionsaufrufe beschreibbar;
  - eine **FIFO-Queue** mit rekursiver Zusammenfassung.
- Bei **70 % Füllstand** kommt eine „memory pressure“-Warnung, damit der Agent Wichtiges selbst auslagert. Bei
  **100 %** wird verdrängt (z. B. 50 %), und es entsteht eine neue rekursive Zusammenfassung. Verdrängtes bleibt
  in **Recall Storage** abrufbar, Beliebiges geht in **Archival Storage** (Z. 232–355).
- **Sleep-time Compute** (Letta): Das Modell „denkt offline“ über einen Kontext nach, bevor die Fragen kommen. Das
  senkte den Test-time-Aufwand um etwa das 5-Fache bei gleicher Genauigkeit (Stateful GSM-Symbolic/AIME) und die
  Kosten je Anfrage um das 2,5-Fache bei mehreren Fragen zum selben Kontext. Lin et al., arXiv 2504.13171 **[V]**
  (Abstract, Z. 21–30). Das ist das direkte technische Gegenstück zur Schlafkonsolidierung.

### B3 A-Mem

Quelle: Xu et al., arXiv 2502.12110. **Venue laut arXiv-Kommentar: NeurIPS 2025** **[V]**.

- Jede Notiz hat die Form `m = {Inhalt, Zeitstempel, LLM-Schlüsselwörter, LLM-Tags, LLM-Kontextbeschreibung,
  Embedding, Links}`.
- **Link-Erzeugung:** zuerst die Top-k nach Kosinus-Ähnlichkeit, **dann entscheidet ein LLM**, welche Links
  sinnvoll sind.
- **Memory Evolution:** Für jeden Nachbarn entscheidet das LLM, ob dessen Kontext, Schlüsselwörter oder Tags
  **aktualisiert** werden. Die neue Fassung ersetzt die alte (Abschnitt 3.1–3.3, Gl. 1–7).

**Abgleich mit vi-mcp:** vi-mcp verknüpft bei **≥ 2 gemeinsamen inhaltlichen Hashtags**
(`gedaechtnis.py:251–261`). Das ist eine deterministische Vereinfachung ohne Embeddings und ohne LLM-Urteil.
**Memory Evolution fehlt.** Sie ist das technische Gegenstück zur Rekonsolidierung (A8).

### B4 HippoRAG

Quelle: Gutiérrez et al., arXiv 2405.14831, **NeurIPS 2024** **[V]**.

- Bildet die hippocampale Indexing-Theorie nach. Ein LLM extrahiert per **OpenIE** einen schemafreien Wissensgraphen;
  das entspricht dem „Neokortex“ bzw. der Mustertrennung.
- Beim Abruf werden die Entitäten der Anfrage als Startknoten gesetzt, und **Personalized PageRank** läuft über den
  Graphen; das entspricht der Musterergänzung.
- Ergebnis: bis zu 20 % besser als der Stand der Technik bei Multi-Hop-QA, 10–20-mal billiger und 6–13-mal schneller
  als iteratives Retrieval (IRCoT) (Abstract, Z. 29–34; Abschnitt 2).

**Abgleich mit vi-mcp:** Die Hashtags und Kanten sind bereits ein Index-Graph. Ausbreitung über Kanten (PageRank)
nutzt vi-mcp beim Abruf nicht. `vertiefe` folgt Hashtag-Häufigkeiten, nicht dem Graphen.

### B5 Reflexion

Quelle: Shinn et al., arXiv 2303.11366 **[V]**.

- Ein Selbstreflexions-Modell formuliert nach einem Fehlschlag **verbal**, was schiefging, und legt das im
  Langzeitgedächtnis ab.
- Der Puffer ist auf **Ω = meist 1–3 Erfahrungen** begrenzt (Z. 405–423).
- 91 % pass@1 auf HumanEval (Abstract, Z. 41).

**Abgleich mit vi-mcp:** Reflexion ist das LLM-Gegenstück zur Regel im Loop („gleicher Fehler ≥ 3× in 24 h“,
`schleife.py:29–43`). Dort steht allerdings eine **Ursachenhypothese** statt einer bloßen Zählung.

### B6 Mem0

Quelle: Chhikara et al., arXiv 2504.19413 **[V]**.

- **Zwei Phasen:**
  1. Extraktion von Fakten aus jedem Nachrichtenpaar.
  2. Update-Phase: Für jeden Fakt werden die Top-s ähnlichen Erinnerungen geholt. Das **LLM wählt dann ADD, UPDATE,
     DELETE oder NOOP** (Z. 152–160).
- Laut den Autoren: +26 % (LLM-as-a-Judge) gegenüber OpenAI-Memory auf LOCOMO, 91 % niedrigere p95-Latenz, über
  90 % weniger Tokens als Full-Context (Abstract). Das ist eine **Selbstauskunft der Autoren**, nicht unabhängig
  geprüft.

**Abgleich mit vi-mcp:** Mem0s **DELETE** widerspricht der Regel „nichts verschwindet still“. vi-mcp setzt
stattdessen `modus = widerlegt` (`gedaechtnis.py:157–162`). Das ist strenger und nachvollziehbarer.

### B7 CoALA

Quelle: Sumers, Yao, Narasimhan & Griffiths, arXiv 2309.02427, **TMLR** (v3 „camera ready“) **[V]**.

- Ein Rahmen nach Soar/ACT-R: **Arbeitsgedächtnis** plus **episodisches, semantisches und prozedurales**
  Langzeitgedächtnis, dazu ein Entscheidungszyklus.
- In prozedurales Gedächtnis (Agentencode) zu schreiben, ist „significantly riskier than writing to episodic or
  semantic memory, as it can easily introduce bugs or allow an agent to subvert its designers' intentions“ (Z. 691–692).
- **Lernen besserer Abrufprozeduren** wird als offenes, wenig erforschtes Feld genannt (Z. 1055–1060).

**Abgleich mit vi-mcp:**
- **Reflexe** (`reflexe.py`, Code im Gedächtnis) sind prozedurales Schreiben, also genau die riskante Klasse. Die
  AST-Prüfung und das Instanz-Recht (`ARCHITEKTUR.md:117–122`) sind die richtige Antwort.
- **Gelernte Suchen** (`suche`) sind gelernte Abrufprozeduren, also die Forschungslücke, die CoALA benennt.

### B8 Persona-Konsistenz und Drift

- **Instruction/Persona Drift:** LLaMA2-chat-70B und GPT-3.5 driften **innerhalb von 8 Runden** deutlich von ihrer
  System-Persona weg. Ursache ist ein **Abfall der Aufmerksamkeit** auf frühe Tokens. Gegenmittel: „split-softmax“.
  Li et al., arXiv 2402.10962, **COLM 2024** **[V]** (Abstract, Z. 17–22).
- **Persona Vectors:** Eigenschaften wie „evil“, Sykophantie oder Halluzinationsneigung sind Richtungen im
  Aktivierungsraum. Damit lassen sich **Schwankungen im Betrieb überwachen**, und Finetuning-Verschiebungen
  korrelieren mit ihnen. Chen et al., arXiv 2507.21509 **[V]** (Abstract, Z. 37–41). Ein Server ohne Zugriff auf die
  Modellgewichte (wie vi-mcp) kann das **nicht** nutzen; das gilt nur für Betreiber mit Gewichtszugriff.
- **Persönlichkeitstests an LLMs** sind unter bestimmten Prompt-Konfigurationen bei einigen Modellen reliabel und
  valide, und die Persönlichkeit ist per Prompt formbar. Serapio-García et al., arXiv 2307.00184 **[A]**.
- **Langzeit-Kohärenz:** In Vending-Bench (über 20 Mio. Tokens je Lauf) haben **alle Modelle Läufe, die
  entgleisen**: Lieferpläne werden missverstanden, Bestellungen vergessen. Backlund & Petersson, arXiv 2502.15840
  **[A]**.

---

## C — Zuordnung: menschlicher Mechanismus → vi-mcp

Legende: ✅ vorhanden · ◐ teilweise · ✗ fehlt. Die Codestellen beziehen sich auf vi-mcp 0.1.1.

| # | Mensch (Quelle) | vi-mcp heute **[C]** | Stand | Vorschlag (konkret) | Messgröße |
|---|---|---|---|---|---|
| 1 | Hippocampus = schneller episodischer Index (A5, Teyler 1986) | `erfahrung` je Handlung mit `daten.vorher`, Kanten zu vorher Gefundenem (`intuition.py:136–151`) | ✅ | Episoden **nur anhängen**: `text`/`daten` einer Erfahrung nach dem Anlegen unveränderlich (Korrespondenz nach Conway) | Test: Ändern einer Erfahrung wird abgelehnt |
| 2 | Neokortex = langsames, abstrahierendes Wissen (CLS 1995/2016) | `erkenntnis` (manuell), `regel` (Loop, nur Fehlerzählung) | ◐ | Schlaf-Loop (Vorschlag 4) destilliert Erkenntnisse **mit Belegkanten** (`kante.grund = "beleg"`) | Anteil der Erkenntnisse mit ≥ 3 Belegen; Quote „bestätigt vs. widerlegt“ von `test`-Erkenntnissen |
| 3 | Schlaf: Triage, Replay, Regelbildung (Stickgold & Walker 2013; Wilhelm 2011; Mattar & Daw 2018) | 60-s-Loop: Antworten löschen, Fehler → Regel, Sichern (`schleife.py:21–55`) | ◐ | Nächtlicher **Konsolidierungslauf** (Schritte unten) | Bericht-Objekt `schlaf:<datum>` mit Zählern; Laufzeit; Fehler = 0 |
| 4 | Vorhersagefehler → Lernen (Schultz 1997; Greve 2017) | Wichtigkeit fest: Fehler = 2, sonst 0 (`intuition.py:148`) | ◐ | **Überraschung** `s = −log₂ P(Ausgang \| tool, host)` aus der Historie mit Laplace-Glättung `P = (k+1)/(n+2)`. Abbildung auf 0–3; neues Werkzeug oder neuer Host ⇒ Neuheit +1 | Korrelation zwischen Wichtigkeit und späterem Abruf mit Erfolg |
| 5 | Testing-Effekt: **erfolgreicher** Abruf stärkt (Roediger & Karpicke 2006) | **Jeder angezeigte** Hinweis wird verstärkt (`o.zugriff()`, `intuition.py:70, 77, 80`) | ⚠ | Verstärkung trennen: `angezeigt` (keine Verstärkung) vs. `genutzt` (Erfahrung danach `ok:ja` **und** Hinweis passte) ⇒ `bestaetigt+1` | **Hinweis-Lift** = P(ok \| Hinweis gezeigt) − P(ok \| gleiches Werkzeug ohne Hinweis) |
| 6 | Vergessen nach Potenzgesetz; Spacing (Wixted & Ebbesen 1991; Pavlik & Anderson 2005) | Exponentiell `0,995^h` seit letztem Zugriff (`gedaechtnis.py:328`) | ◐ | Tabelle `abruf(objekt_id, zeit, art, gespraech, erfahrung_id)` und **Aktivierung nach ACT-R** `A = ln Σ (Δt_j)^(−d)`. Optional ein `d_j` je Abruf, das von der Aktivierung im Moment des Abrufs abhängt (Pavlik & Anderson), damit Spacing von selbst entsteht | Vergleich der Rangfolge alt/neu auf denselben Anfragen; Hinweis-Lift vorher/nachher |
| 7 | Vergessen als Funktion (Richards & Frankland 2017) | Nur `antwort` wird gelöscht (`schleife.py:27–28`); alles andere bleibt für immer | ✗ | **Archiv-Stufe**: Erfahrungen mit A < θ, älter als T, ohne Belegkante zu Erkenntnis/Regel ⇒ `modus = archiviert` (neuer, benannter Modus), `daten` komprimiert in eine Tabelle `archiv`, Stummel mit Text und Hashtags bleibt | DB-Größe, p95-Latenz von `erinnere`, Anteil archiviert; „verschwunden“ = 0 |
| 8 | Abrufinduziertes Vergessen / Konkurrenz (Anderson et al. 1994) | Durch Punkt 5 gerade **umgekehrt**: Gezeigtes rückt nach vorne (`zuletzt = jetzt`), wird wieder gezeigt (Matthäus-Effekt) | ⚠ | Mit Vorschlag 5 behoben; zusätzlich Kandidatenvorauswahl nicht nur `ORDER BY zuletzt DESC LIMIT 400` (`gedaechtnis.py:319`) | **Gini-Koeffizient** der Zugriffe; Anteil „nie gezeigter“ aktiver Erkenntnisse |
| 9 | Arbeitsgedächtnis ≈ 4 Chunks (Cowan 2001) | `vorher` liefert bis zu 4 Erkenntnisse/Regeln + 3 Suchen × 3 Treffer + Reflex-Hinweise (`intuition.py:69–84`) | ◐ | Gesamtbudget von **≤ 4 Hinweisen**, nach Score sortiert; Rest per `vi_vertiefe` auf Abruf (Progressive Disclosure) | Hinweise pro `vorher` (Mittel, p95); Hinweis-Lift je Rangplatz |
| 10 | Enkodierungsspezifität / Kontext (Tulving & Thomson 1973; Godden & Baddeley 1975) | Reize: `tool:`, `skill:`, `host:`, `instanz:` (`ARCHITEKTUR.md:89`) | ◐ | Reize um **`projekt:`** (Arbeitsverzeichnis) und **`aufgabe:`** (vom Client gemeldet) erweitern; Treffer mit Kontextgleichheit höher gewichten | Hinweis-Lift bei Kontext-Gleichheit vs. -Ungleichheit |
| 11 | Ereignisgrenzen (Zacks 2007; EM-LLM) | Episode = ganzes Gespräch (`sitzung.py:116–142`) | ◐ | Grenze im Gespräch bei Wechsel von `skill:`/`host:` **oder** Pause > 10 min ⇒ Unterepisode `abschnitt:<n>` als Hashtag | Mittlere Episodenlänge; Treffergenauigkeit von `vi_gespraech` |
| 12 | Schemata beschleunigen Konsolidierung (Tse 2007; Kumaran 2016) | — | ✗ | Im Schlaf: Passt ein Cluster zu einer bestehenden Erkenntnis (gleiche Hashtags, gleicher Ausgang) ⇒ `bestaetige` (Grund: „n neue Belege“). Widerspricht er ⇒ Konflikt (Punkt 13) | Konflikte/Woche; Zeit vom ersten Beleg bis zur Erkenntnis |
| 13 | Rekonsolidierung: Abruf plus Vorhersagefehler ⇒ veränderbar (Nader 2000; Sinclair & Barense 2019; A-Mem Evolution) | Nur `widerlege` (ganz oder gar nicht, `gedaechtnis.py:157–162`) | ◐ | Zwischenstufe: gezeigter Hinweis, danach **unerwarteter** Ausgang ⇒ Hashtag `konflikt:offen` + Eintrag „Einschränkung vorgeschlagen“ (z. B. `!host:x`) im Modus `test`; erst Mensch oder Wiederholung entscheidet | Offene Konflikte; mittlere Liegezeit |
| 14 | Emotionale Salienz / langsameres Vergessen (McGaugh 2004; Yonelinas & Ritchey 2015) | Wichtigkeit 0–3 additiv im Score | ◐ | Für Agenten heißt Salienz: **menschliche Korrektur**, Datenverlust, Sicherheitsereignis ⇒ Wichtigkeit 3 **und** kleinere Zerfallsrate `d` | Abrufrate von Wichtigkeit-3-Objekten nach 30 Tagen |
| 15 | Working Self / Self-Memory System (Conway 2000/2005; Strohminger & Nichols 2014) | — (Park: gecachter „Summary Description“, Anhang A) | ✗ | **Selbst-Objekt** (Datenstruktur unten), bei jedem `initialize` geladen, änderbar nur mit Grund und Belegen | Drift-Messungen (D4) |
| 16 | Prozedurales Gedächtnis (Squire 2004; CoALA) | `reflex` (Code), `suche` (Abrufprozedur) | ✅ | Unverändert. Im Schlaf zusätzlich: Suchen, deren Treffer nie genutzt wurden, ⇒ `modus = test` vorschlagen | Nutzungsquote je Suche |
| 17 | Indexing / Musterergänzung (Teyler 1986; HippoRAG) | Kanten existieren, werden beim Abruf nicht verfolgt | ◐ | Personalized PageRank (oder 1–2 Sprünge) ab den Treffern über `kante` als dritte Relevanzquelle | Recall auf einer festen Testfrage-Liste |

### C1 Datenstruktur „Selbst“ (Vorschlag)

Ein Objekt mit `art = "selbst"` und fester ID `selbst:kern`. Dafür muss `ARTEN` in `gedaechtnis.py:31` erweitert
werden. Die Teile werden nach **Intension und Extension getrennt**:

```json
{
  "version": 7,
  "soll": {                       // Intension — nur Mensch oder belegter Vorschlag + Bestätigung
    "werte":   [{"satz": "Erst prüfen, dann ändern", "seit": "2026-11-08", "belege": ["erkenntnis:…"], "quelle": "Auftraggeber"}],
    "ziele":   [{"satz": "…", "prioritaet": 1}],
    "stil":    [{"satz": "Deutsch, knapp, jede Aussage mit Beleg"}],
    "grenzen": [{"satz": "Schreibt nie selbst; schreibende Werkzeuge nie aus dem Gedächtnis"}]
  },
  "ist": {                        // Extension — vom Schlaf-Loop aus Daten berechnet, nie von Hand
    "kompetenz": [{"bereich": "skill:netbox", "erfahrungen": 412, "erfolgsquote": 0.94, "zeitraum": "30 d"}],
    "schwaechen": [{"bereich": "host:app0815", "fehler": "fehler:timeout", "n": 9}],
    "beziehungen": [{"instanz": "laptop", "gespraeche": 31, "zuletzt": "…"}]
  },
  "erzaehlung": "≤ 150 Wörter, aus soll+ist erzeugt (Park, Anhang A), nie Quelle eigener Fakten"
}
```

- **Änderung** nur über eine neue Methode `aendere_selbst(pfad, neu, grund, belege)`. Pflicht sind ein Grund und
  **≥ 3 Belege aus ≥ 2 verschiedenen Tagen** (Spacing statt Burst).
- Für `soll` gilt zusätzlich: Ein Vorschlag landet im Modus `test` und wird erst mit `vi_bestaetige` durch einen
  Menschen wirksam.
- **Geschichte:** eine eigene Tabelle `selbst_version(version, zeit, wer, diff, grund, belege)`. Die
  `aenderungen`-Liste eines Objekts **reicht nicht**: Sie wird auf die letzten 50 Einträge gekürzt
  (`gedaechtnis.py:137`, `[-50:]`). Das verstößt bei langlebigen Objekten gegen „nichts verschwindet still“.
- **Auslieferung:** `erzaehlung` plus `soll` gehen in das `instructions`-Feld der `initialize`-Antwort. Dass die
  MCP-Spezifikation ein solches Feld hat, ist **[E]**; zu prüfen in
  https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle.
  Wegen der Drift nach wenigen Runden (Li et al. 2024) wird es zusätzlich **alle N `vorher`-Aufrufe** als kurzer
  Hinweis wiederholt.

### C2 Konsolidierungslauf „Schlaf“ (Vorschlag)

**Auslöser:**
- einmal pro Nacht, z. B. 03:00 Ortszeit;
- **oder** sobald die Summe der Wichtigkeit neuer Erfahrungen seit dem letzten Lauf eine Schwelle `S` überschreitet
  (Parks Reflexions-Trigger, auf die Skala 0–3 umgerechnet; `S` ist ein Startwert zum Kalibrieren, z. B. 40).

Er läuft im **einen** vorhandenen Loop-Thread, also ohne zweiten Schreiber (`ARCHITEKTUR.md:34`).

1. **Triage** (Stickgold & Walker; Wilhelm; Mattar & Daw): Alle Erfahrungen seit dem letzten Lauf bekommen eine
   Priorität `p = Überraschung + Wichtigkeit/3 + Zukunftsrelevanz`.
   - Zukunftsrelevanz = 1, wenn die Reize der Erfahrung in einer aktiven `suche` oder `regel` vorkommen oder der
     Host in den letzten 7 Tagen ≥ 3× auftrat.
2. **Replay, verschränkt** (CLS 1995): Die Top-Erfahrungen werden nach inhaltlichen Hashtags gruppiert, also nach
   (`tool`, `fehler`), (`host`) und (`skill`). **Je Cluster kommen k ältere Erfahrungen derselben Hashtags hinzu.**
   So wird das Neue gegen das Alte gelesen und überschreibt es nicht.
3. **Schema-Abgleich** (Tse 2007): Gibt es zum Cluster eine Erkenntnis oder Regel?
   - Gleicher Ausgang ⇒ `bestaetige` mit Grund.
   - Gegenteiliger Ausgang ⇒ `konflikt:offen` (Punkt 13), **keine** stille Änderung.
4. **Abstraktion** (Park, Abschnitt 4.2): Ein Cluster ohne Schema mit ≥ 3 Erfahrungen an ≥ 2 Tagen wird zur neuen
   `erkenntnis` im Modus `test`, mit **Belegkanten** zu jeder Erfahrung.
   - Die deterministische Variante formuliert aus Vorlagen.
   - Die LLM-Variante formuliert über das lokale Modell. Auf dem Produktivhost (<host>) laufen laut `CHANGELOG.md` (0.1.1) die
     Routen `/health/qwen35b` und `/health/embed`; ob sie dafür geeignet sind, ist ungeprüft.
   - Dabei gilt CLAUDE.md: **kein `max_tokens`**, bei Abschneiden Thinking abschalten.
   - Grundsatzfrage: „Die VI handelt nie selbst“ (`ARCHITEKTUR.md:84`). Ein interner LLM-Aufruf ist keine Handlung in
     der Welt, sollte aber ausdrücklich als Ausnahme dort stehen.
5. **Vergessen/Archiv** (Richards & Frankland): Erfahrungen mit Aktivierung < θ, älter als T (Start: 30 d) und ohne
   Belegkante werden `archiviert`. Erkenntnisse und Regeln werden **nie** automatisch archiviert.
6. **Selbst-Revision:** `ist` wird neu berechnet. Für `soll` werden höchstens Vorschläge im Modus `test`
   erzeugt.
7. **Bericht:** Ein Objekt `schlaf:<datum>` hält die Zähler je Schritt, Dauer, Fehler und die IDs neuer oder
   geänderter Objekte. `vi_status` zeigt den letzten Bericht (zureichender Grund).

### C3 Woran man merkt, ob es wirkt

Jede Zahl wird mit Zeitraum und Herkunft gemessen, alles per SQL auf `vi.db`.

| Messgröße | Definition | Erwartung, wenn es wirkt |
|---|---|---|
| **Wiederholungsfehlerquote** | Anteil fehlgeschlagener Erfahrungen, deren `(tool, fehler)` schon als Regel oder Erkenntnis existierte **und** vorher als Hinweis gezeigt wurde | sinkt über Wochen |
| **Hinweis-Lift** | P(ok:ja \| Hinweis) − P(ok:ja \| gleiches Werkzeug, kein Hinweis) | > 0 und steigend |
| **Hinweis-Last** | Hinweise je `vorher` (Mittel, p95) | ≤ 4 |
| **Konsolidierungsgüte** | `test`-Erkenntnisse aus dem Schlaf: bestätigt / (bestätigt + widerlegt) | hoch und stabil; fällt sie, ist die Abstraktion schlecht |
| **Zugriffsungleichheit** | Gini der `zugriffe` über aktive Erkenntnisse | darf nicht stetig steigen (Matthäus-Effekt, Punkt 8) |
| **Selbst-Stabilität** | Änderungen an `soll` je Monat; Anteil mit ≥ 3 Belegen | wenige, 100 % belegt |
| **Verschwunden** | Objekte, die ohne Eintrag `archiviert`/`widerlegt`/`gelöscht` fehlen | immer 0 |

---

## D — Risiken und Grenzen

### D1 Anthropomorphismus

- Wer Dialogsysteme vermenschlicht, verleitet zu **übermäßigem Vertrauen** in ihre Ausgaben. Abercrombie et al. 2023,
  „Mirages“, EMNLP, arXiv 2305.09800 **[A]**.
- Shanahan rät, über LLMs ohne mentalistische Begriffe zu sprechen. CACM 67:68–79, doi:10.1145/3624724 **[T]**.
- Shanahan, McDonell & Reynolds beschreiben LLM-Dialoge als **Rollenspiel** eines Simulators. *Nature* 623:493–498,
  doi:10.1038/s41586-023-06647-8 **[T]**. Die Inhalte beider Arbeiten sind **[E]**.
- **Folgerung:** „Intuition“, „Bewusstsein“ und „Schlaf“ sind in vi-mcp **Metaphern für Mechanismen**. Die Doku
  sollte das sagen; `ARCHITEKTUR.md:7–10` tut es implizit über die Spalte „Im Code“. Behauptungen über Erleben oder
  Empfinden sind nicht gedeckt.

### D2 Was „Persönlichkeit“ hier heißen kann und was nicht

- **Kann:** ein über Sitzungen **konsistentes Verhaltensprofil**. Dazu gehören stabile Werte und Stil (`soll`), aus
  Daten belegte Kompetenzen und Schwächen (`ist`) und ein gemeinsames Erfahrungsgedächtnis über alle Instanzen.
  Dass Persönlichkeitsmessungen an LLM-Ausgaben unter Bedingungen reliabel und prompt-formbar sind, zeigen
  Serapio-García et al. 2023 **[A]**. Damit ist es auch **messbar**.
- **Kann nicht:**
  - Das Modell selbst lernt nicht. Die Gewichte, also der eigentliche „Neokortex“, bleiben fest. Konsolidierung
    erzeugt **Text**, keine Gewichtsänderung.
  - Dasselbe Selbst-Objekt wird von **verschiedenen Modellen** (Claude, Qwen, GPT) gelesen und unterschiedlich
    umgesetzt. Die Persönlichkeit ist dann eine Eigenschaft von *Gedächtnis plus Modell*, nicht des Gedächtnisses
    allein.
  - Die Identitätsforschung (Strohminger & Nichols 2014) legt nahe, Konsistenz an **Werten** festzumachen, nicht an
    der Menge der Erinnerungen. Das ist eine **Hypothese** für die Übertragung auf Agenten.

### D3 Datenschutz und Sicherheit

- Gespeichert werden Gesprächsverläufe (`gespraech_roh`, zlib) und Werkzeugergebnisse bis 200 000 Zeichen
  (`intuition.py:152`), darin „können Zugangsdaten stehen“ (`ARCHITEKTUR.md:131–132`). Die Dateirechte 0600/0700
  sind gesetzt (`gedaechtnis.py:62–76`).
- **DSGVO** (https://eur-lex.europa.eu/eli/reg/2016/679/oj):
  - Datenminimierung und Speicherbegrenzung (Art. 5 Abs. 1 lit. c, e);
  - Recht auf Löschung (Art. 17).

  Die Artikelnummern sind **[E]** und an der URL zu prüfen.
- **Lücke:** `vi_vergiss` verwirft nur gemerkte Antworten eines Werkzeugs (`werkzeuge.py:62`). Ein **Löschen nach
  Person, Gespräch oder Inhalt** fehlt.
- **Konflikt mit „nichts verschwindet still“:** Er lässt sich mit einem **Grabstein** auflösen. Der Inhalt wird
  gelöscht, ein Objekt `gelöscht` bleibt (wer, wann, Grund, Anzahl), ohne Inhalt.
- **Vorschlag:** Vor dem Speichern bekannte Geheimnismuster maskieren (Tokens, Passwörter, Header
  `Authorization`), mit dem Hashtag `geschwaerzt:n`.
- **Gedächtnis-Vergiftung:** Angreifer können über bloße Anfragen bösartige Einträge in das Gedächtnis eines Agenten
  schleusen (MINJA, Dong et al., arXiv 2503.03704 **[A]**). Das Gedächtnis selbst lässt sich auch gezielt
  vergiften (AgentPoison, Chen et al., arXiv 2407.12784 **[A]**).

  Bei einem **gemeinsamen** Gedächtnis vieler Instanzen ist das zentral. vi-mcp hat bereits drei Schutzlinien:
  Herkunft (`instanz:`), Modus `test` für Abgeleitetes und das Reflex-Recht je Instanz. **Vorschlag:**
  - Gelerntes einer Instanz wirkt für andere Instanzen erst nach Bestätigung (Quarantäne);
  - das Selbst-Objekt (`soll`) ist nur durch Menschen bestätigbar.

### D4 Drift erkennen

- **Innerhalb einer Sitzung:** Instruktionen verblassen nach wenigen Runden (Li et al. 2024 **[V]**). Gegenmittel:
  das Selbst periodisch wieder einspielen (C1).
- **Über Wochen** (Gedächtnisdrift): Selbstbestätigung (Punkt 8), sich selbst verstärkende Reflexionen (Park:
  Reflexionen über Reflexionen, Abschnitt 4.2 **[V]**), ausgeschmückte Erinnerungen (Park, Abschnitt 6.5.2 **[V]**)
  und Selbstbeschönigung (Wilson & Ross 2003 **[A-tldr]**). Messpunkte:
  1. **Belegquote:** Jede Erkenntnis und jede Selbst-Aussage braucht Belegkanten zu **Erfahrungen**, nicht nur zu
     anderen Erkenntnissen. Reflexionsketten ohne Erfahrungsbezug werden markiert.
  2. **Probe-Batterie:** 10–20 feste Fragen („Was tust du bei …?“, „Wie gehst du mit … um?“). Sie werden monatlich
     in einer frischen Sitzung beantwortet und mit der Vorversion verglichen: semantische Ähnlichkeit (über den
     Embedding-Dienst, falls geeignet) plus Sichtprüfung durch einen Menschen.
  3. **Selbst-Diff:** Jede Version von `selbst_version` wird angezeigt. Eine Änderung ohne Belege ist **unmöglich**
     (Typ-Ebene, nicht erst im UI).
  4. **Modellwechsel-Test:** Dieselbe Probe-Batterie läuft mit zwei Modellen auf demselben Gedächtnis. Was sich
     unterscheidet, gehört dem Modell, nicht der VI.

---

## Top 5 Vorschläge für vi-mcp (nach Nutzen/Aufwand)

1. **Verstärken nur bei Nutzen, Abruf-Protokoll und Messpunkte.** Aufwand: klein.
   - In `vorher` wird angezeigt, aber **nicht** verstärkt (`intuition.py:70, 77, 80`).
   - In `nachher` wird `bestaetigt+1` für die Hinweise gesetzt, wenn die Handlung `ok:ja` war.
   - Neue Tabelle `abruf(objekt_id, zeit, art, gespraech, erfahrung_id)`.
   - Hinweis-Budget von 4.
   - `vi_status` zeigt Hinweis-Lift, Wiederholungsfehlerquote und Gini.

   *Warum zuerst:* Das beseitigt die Selbstbestätigung (Logikregel 5, Testing-Effekt A10), und ohne diese Messpunkte
   ist keiner der anderen Vorschläge prüfbar.
2. **Überraschung statt fester Wichtigkeit.** Aufwand: klein.
   `wichtigkeit` aus `−log₂ P(Ausgang | tool, host)` mit Laplace-Glättung, dazu ein Neuheitsbonus
   (`intuition.py:148`). Ein Fehler bei einem sonst zuverlässigen Werkzeug wird wichtig, ein chronischer Fehler
   gewöhnt sich ab (A7).
3. **Selbst-Objekt mit `soll`/`ist`-Trennung und Versionstabelle** (C1). Aufwand: mittel.
   Wird bei `initialize` ausgeliefert und periodisch wiederholt. `soll` ist nur mit Grund, Belegen und menschlicher
   Bestätigung änderbar. Das ist der eigentliche Kern der „virtuellen Persönlichkeit“ (A12, B1 Anhang A, B8).
4. **Schlaf-Konsolidierung, zunächst deterministisch** (C2, Schritte 1–4 und 7). Aufwand: mittel.
   Triage, verschränktes Replay, Schema-Abgleich und Erkenntnisse mit Belegkanten im Modus `test`. Die LLM-Formulierung
   kommt erst, wenn die Konsolidierungsgüte (C3) gemessen ist.
5. **Vergessen als Funktion: ACT-R-Aktivierung und Archiv-Modus** (C 6–7; C2 Schritt 5). Aufwand: mittel.
   Potenzgesetz statt `0,995^h`, Spacing aus dem Abruf-Protokoll, `archiviert` als benannter Modus mit Stummel.
   Dazu ein Löschen nach Gespräch mit Grabstein (D3).

**Nebenbefunde zum Korrigieren in der Doku** (nichts geändert):
- `ARCHITEKTUR.md:76`: Der Faktor 0,995 ist im Paper belegt (Abschnitt 4.1), aber **je Spielstunde** (≈ 1 min
  Echtzeit, Anhang A). vi-mcp verwendet Echtzeit-Stunden, also eine Halbwertszeit von ≈ 5,8 Tagen. Park normiert die
  drei Komponenten zudem per Min-Max, vi-mcp nicht.
- `gedaechtnis.py:137`: Die Änderungsgeschichte wird auf 50 Einträge gekürzt. Bei langlebigen Objekten verschwindet
  Geschichte still.
- `ARCHITEKTUR.md:67`: „A-Mem“ verknüpft im Original per Embedding und LLM-Urteil und aktualisiert die Nachbarn
  (Memory Evolution). vi-mcp übernimmt nur die Zettelkasten-Idee.
