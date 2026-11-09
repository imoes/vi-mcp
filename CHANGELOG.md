# Changelog

Was ein Nutzer von vi-mcp merkt — gruppiert nach Wirkung, jeder Eintrag mit Nachweis.
Verlinkt aus [README.md](README.md).

## 0.20.7 — 2026-11-09 — Regeln, wann eine KI die VI befragt und wann sie lernt

### Was ist neu

- **Jeder Client bekommt beim Verbinden feste Regeln** (MCP `instructions`, eine Quelle: `werkzeuge.REGELN`). Vorher stand dort nur, was die
  Werkzeuge tun, nicht wann man sie nutzt.
  - *Befragen:* vor Beginn jeder Aufgabe (Hosts, Systeme, Produkte, Fehlermeldungen der Aufgabe); vor jeder ändernden Handlung an einem
    System; bei Fehlern, bevor man selbst sucht; bei Fragen zu internen Systemen zuerst die VI. Automatische Hinweise vor einer Handlung
    sind schon Treffer.
  - *Lernen:* nach einem gelösten, nicht offensichtlichen Problem; wenn der Nutzer eine bleibende Regel nennt; nach nachgeschlagenen oder
    gemessenen Systemfakten; Korrekturen (dazu falsches Wissen widerlegen). Vorher suchen, Vorhandenes bestätigen statt doppelt anlegen.
  - *Nie lernen:* Geheimnisse, Unbelegtes, Flüchtiges, was im Repository gepflegt wird. Firmenwissen mit `sicht=intern`.
  - Ohne Token kommt ein Zusatz dazu: Bestätigen, Widerlegen und `sicht=intern` brauchen ein Token — die Regeln verlangen nichts, was
    danach abgelehnt würde.
- Die Beschreibungen von `vi_erinnere` und `vi_lerne` nennen jetzt das „Wann“.
- *Nachweis:* `init()` in `tests/test_http.py` prüft die Regeln in den `instructions` jeder HTTP-Sitzung;
  `test_regeln_ohne_token_verlangen_nichts_unmoegliches`.

### Was fehlt noch

- Ob die Regeln befolgt werden, ist nicht gemessen. Beobachtungspunkt: Anteil der Sitzungen mit `vi_erinnere` vor der ersten ändernden
  Handlung und Zahl der `vi_lerne` je Sitzung (aus den Erfahrungen ablesbar).

## 0.20.6 — 2026-11-09 — Semantische Kanten mit Obergrenze

### Was wurde behoben

- **Fast gleiche Texte verbanden sich alle miteinander.** Nach dem Confluence-Import hatte das Produktivsystem 2.315.212 Kanten „semantisch
  ähnlich“, bis zu 1.346 je Objekt; der Nähe-Schritt brauchte 96 s je Trainingslauf und die Datenbank wuchs auf 780 MB. Ursache: jede Nähe
  ≥ 0,85 wurde zur Kante, ohne Grenze — viele Vorlagenseiten haben dieselbe Kernaussage (cos 1,00). Jetzt bekommt ein neuer Vektor höchstens
  10 Nachbarn, und bestehende semantische Kanten werden auf **gegenseitige** nächste Nachbarn gekappt (ein Paar bleibt, wenn jede Seite die
  andere unter ihren 10 ähnlichsten hat). Belege und Hashtag-Kanten bleiben unberührt; die Zahl gelöschter Kanten steht im Bericht (`gekappt`).
- *Nachweis:* an einer Kopie der Produktivdatenbank (09.11. 07:44 UTC): 2.267.336 Kanten gekappt in 17,1 s (einmalig), danach 47.876,
  höchstens 10 je Objekt, 9.780 von 12.058 Objekten mit Vektor behalten mindestens eine; zweiter Aufruf 0,16 s, nichts zu tun.
  Test `test_semantische_kanten_haben_eine_obergrenze`.

### Was fehlt noch

- Die Kernaussage (`text`) vieler importierter KB-Abschnitte ist ein Vorlagensatz („Hier können betriebliche Notizen … eingetragen werden“);
  eingebettet wird nur `text`, also sehen diese Abschnitte für die Bedeutungssuche gleich aus. Der Fehler liegt im Importskript (erster Absatz
  > 40 Zeichen als Kernaussage); der Volltext über `inhalt` ist davon nicht betroffen. Korrektur braucht ein Werkzeug, das `text` eines
  bestehenden Objekts ändert.

## 0.20.5 — 2026-11-09 — Der Schlaf hält nichts mehr an

### Was wurde behoben

- **Der Schlaf läuft in einem eigenen Thread.** Bisher lief er synchron im Loop und hielt über die Trainingssperre auch das Training bei
  Bedarf an. Auf dem Produktivsystem dauerte ein Schlaf 429–530 s (09.11.), Schritt 7 durfte bis 1.200 s einbetten. Nach dem Neustart um
  06:43 UTC stand der Loop 20 Minuten lang bei 1 Lauf, das Training bei 2. Jetzt prüft der Loop weiter im Minutentakt und startet keinen
  zweiten Schlaf, solange einer läuft. *Nachweis:* `test_schlaf_haelt_den_loop_nicht_an` (schlägt mit 0.20.4 fehl).

### Was hat sich geändert

- **Einbettung mit Pausen, wählbar:** Mit `embed.pause_anteil` = 1.0 wartet die VI nach jedem Batch so lange, wie der Batch gedauert hat.
  Standard ist 0 = ungedrosselt (Entscheidung des Nutzers am 09.11.). Der Embedding-Dienst ist geteilt; eine einzelne kurze Frage brauchte dort am 09.11. um 07:00 UTC 23–27 s, um 06:13 UTC
  1,9–6,5 s. Ob die VI die Ursache war, ist **nicht belegt** (ein Gegenversuch ergab 56,8 / 4,4 / 0,06 s). Eingeschaltet halbiert die Pause
  höchstens den eigenen Durchsatz (gemessen rund 1.550 Vektoren je Stunde). Der Schlaf bettet höchstens 300 s statt 1.200 s ein, den Rest übernimmt
  das Training bei Bedarf. Der Bericht nennt `pause_s`. *Nachweis:* `test_einbettung_pausiert_zwischen_batches`.
- **Firmendoku, nachgeholt mit dem lokalen Richter** (09.11. ~07:20 UTC, dieselben 6 Fragen und dieselbe Abfrage wie in den Läufen 2/3):
  VI 3× ja, 1× teilweise, 2× nein = **3,5 von 6** (AIKB bester Lauf 4 von 6, Lauf 3 0 von 6). Die eigene Bewertung aus 0.20.4 (4 von 6)
  war also um 0,5 zu hoch, je nach Lesart: Bei der VPLEX-Frage urteilte der Richter „nein“, obwohl er in seiner Begründung zitiert, dass
  „NUR die VPLEX1, NICHT die VPLEX2“ im gelieferten Text steht; bei NiFi „teilweise“ (nur Verweis auf ein PDF). Das Urteil des Richters
  zählt, die Unstimmigkeit steht hier.
- Gemessen (09.11. 07:00 UTC, 6 Fragen): Suche nur im Volltext 0,08–0,16 s; hybrid 20,6–25,4 s, davon Einbettung der Frage 20,3–25,1 s.
  Die Zeit der Bedeutungssuche liegt fast ganz im Embedding-Dienst, nicht in der VI.

## 0.20.4 — 2026-11-09 — Fehlende Pflichtfelder werden abgelehnt

### Was wurde behoben

- **Ein Werkzeugaufruf ohne Pflichtfeld wird abgelehnt und nennt das Feld**, statt still mit Standardwerten zu antworten. Am 09.11. lieferte
  `vi_erinnere` mit `text` statt `filter` die fünf wichtigsten Objekte — sechs Vergleichsfragen sahen aus wie beantwortet, waren aber nie gesucht
  („5 Objekte zu „““). Jetzt: `vi_erinnere: Pflichtfeld fehlt: filter — übergeben, aber unbekannt: text`. Geprüft wird gegen das `required` des
  Werkzeug-Schemas, für alle Werkzeuge. *Nachweis:* `test_fehlendes_pflichtfeld_wird_abgelehnt_statt_still_beantwortet` (schlägt mit 0.20.3 fehl).

### Gemessen: Firmendoku nach dem Import

- Nach dem Import von rund 10.000 Abschnitten aus einem internen Confluence-Space (Sicht `intern`) beantwortet die VI **4 von 6** Firmendoku-Fragen
  aus dem Vergleich vom 08./09.11. (vorher 0 von 6), dieselben vier wie die AIKB in ihrem besten Lauf (4 von 6; im zweiten Lauf 0 von 6, alle sechs
  Anfragen nach 300 s abgebrochen). Die Kernaussage steht jeweils inhaltlich im Treffer (Platz 1–3, im Volltext des Objekts geprüft). Die VI meldete
  für die Einbettung der Frage 1,9–6,5 s (Gesamtzeit nicht gemessen); die AIKB brauchte 57–300 s. Zwei der vier Treffer kamen nur über den Volltext, weil ihr Vektor noch fehlte (Einbettung hinkt dem
  Import hinterher, gemessen rund 1.550 Vektoren je Stunde).
- **Einschränkung:** Bewertet hat diesmal Claude anhand des Trefferinhalts, nicht das lokale Sprachmodell wie in den früheren Läufen — es lieferte
  ab 05:04 UTC nur noch unbrauchbare Ausgaben. Die Bewertung mit dem lokalen Richter wird nachgeholt.
- Nicht gefunden: eine Frage zu Elasticsearch-Shards (auch die AIKB nicht); eine Seite (NiFi) verweist nur auf ein PDF, die Kernaussage steht nicht im Text.

## 0.20.3 — 2026-11-09 — Kein fester Nachtlauf mehr

### Was hat sich geändert

- **Der Nachtlauf um 03:00 UTC ist nur noch ein Sicherheitsnetz:** Er läuft, wenn seit 24 Stunden kein Schlaf lief. Trainiert wird seit 0.20.0 bei Bedarf;
  geschlafen wird, sobald die Wichtigkeit neuer Erfahrungen 40 erreicht (auf dem Produktivsystem in der Nacht zum 09.11. etwa alle 10–80 Minuten).

### Was wurde behoben

- Der Nachtlauf fiel still aus, sobald am selben Kalendertag schon ein Schlaf gelaufen war. Am 09.11. liefen Schläfe um 00:28, 01:50, 02:00, 02:10 und
  02:44 UTC; um 03:00 passierte nichts, und das stand nirgends. *Nachweis:* `test_nachtlauf_nur_wenn_24_h_kein_schlaf` (schlägt mit 0.20.2 fehl).

## 0.20.2 — 2026-11-09 — Fallstricke von Alltagswerkzeugen werden erkannt

### Was wurde behoben

- **`pkill`, `grep`, `sed`, `find`, `chmod`, `kill` usw. sind wieder Reize.** Die Liste „Shell-Alltag“ aus 0.19.4 war zu breit: Eine gelernte Warnung zu
  `pkill -f` (trifft die eigene Shell, Exit 144) erschien vor `pkill -f …` nur zufällig, die Reize waren bloß `tool:Bash`. Gefunden auf dem Produktivsystem
  am 09.11. Ohne Reiz bleiben nur Befehle ohne fachliche Aussage (cd, ls, echo, cat, head, sleep …) und Interpreter (sh, bash, python3).
- **Vorsätze werden übersprungen wie `sudo`:** `timeout 300`, `setsid`, `nohup`, `nice -n 10`, `ionice`, `stdbuf`, `env X=1`. Vorher wurde aus
  `timeout 300 ssh host 'vzdump 101'` nur `thema:timeout`; Host und vzdump fehlten.
- *Nachweis:* vier neue Fälle in `test_befehle_werden_reize`; mit 0.20.1 schlagen 6 Fälle fehl.

## 0.20.1 — 2026-11-09 — Verschachtelte Anführungszeichen

### Was wurde behoben

- Code in Anführungszeichen **innerhalb** eines ssh-Befehls wurde als Shellbefehl gelesen: Aus `ssh host 'curl … | python3 -c "import json; …print(…)"'`
  wurden die Reize `thema:import`, `thema:print`, `thema:for`, `thema:sys.stdin`. Gesehen im Hook auf dem Produktivsystem (09.11., kurz nach 02:20 UTC).
  Ein Stapel hält jetzt jede Ebene von Anführungszeichen; innerer Text ist nur ein Befehl, wenn auch er ausgeführt wird (`sh -c "…"` innerhalb `ssh '…'`).
  *Nachweis:* zwei neue Fälle in `test_befehle_werden_reize`, der erste schlägt mit 0.20.0 fehl.

## 0.20.0 — 2026-11-09 — Lernen bei Bedarf, Sicht „intern“ für Firmenwissen

### Was ist neu

- **Training bei Bedarf statt nur nachts** (`bedarf.py`). Jede gemeldete Handlung mit Ergebnis und jedes gelernte Wissen stoßen einen
  Hintergrund-Lauf an, frühestens 60 s nach dem letzten. Der Lauf bettet fehlende Vektoren ein (bis 120 s je Lauf, ein Rest läuft gleich weiter),
  zieht Nähe-Kanten für die neuen Vektoren, berechnet nach 200 neuen Vektoren die Inhaltsgruppen neu und trainiert Bandit und Router.
  `vi_status` zeigt Läufe, Grund und Dauer je Schritt. Der Schlaf behält Reflexion, Abstraktion, Skills, Scorer und Lager; beide teilen sich
  eine Sperre. *Gemessen auf einer Kopie der Produktivdaten (5.118 Objekte, 1.310 Beobachtungen):* Router 68–487 ms, Bandit 30 ms,
  KMeans 2,4 s, ganzer Lauf ohne neue Vektoren 0,5 s. *Nachweis:* `tests/test_bedarf.py` (4 Tests, u. a. der Thread läuft nach einem Anstoß).
- **Sicht `intern`** (`vi_lerne(sicht="intern")`): sichtbar für jede Instanz mit Token, nie für die tokenlose Instanz im Open-Wiki-Modus und nie
  im P2P-Netz. Für Firmenwissen wie Confluence, das sonst ohne Anmeldung lesbar wäre. *Nachweis:* `test_internes_sieht_nur_wer_ein_token_hat`
  (Suche, Bedeutungssuche, Hinweise, `vi_objekt` ohne Token leer; mit Token sichtbar; auch bewährt nicht im Netz-Export),
  `test_ungueltige_sicht_wird_abgelehnt`; beide schlagen mit 0.19.5 fehl.

### Was hat sich geändert

- **Nähe-Kanten inkrementell:** Nur noch nicht verglichene Vektoren werden gegen alle geprüft (Spalte `vektor.verglichen`, wird beim ersten
  Start nachgerüstet). Gemessen: voller Vergleich 3.312 Vektoren 9,6 s (0.19.x) → 2,1 s (erster Lauf 0.20.0) → 21 ms ohne neue Vektoren.
  Vorher wuchs die Dauer mit dem Quadrat der Objektzahl; nach einem großen Import wären es geschätzt eine Viertelstunde und mehr gewesen.
  *Nachweis:* `test_naehe_kanten_vergleichen_nur_neue`.

## 0.19.5 — 2026-11-09 — Frisch Gelerntes ist sofort auffindbar

### Was hat sich geändert

- **`vi_erinnere` mit `semantisch=true` sucht hybrid.** Die Bedeutungs- und die Volltext-Rangliste werden per Reciprocal Rank Fusion
  (Cormack et al. 2009, k = 60) zusammengeführt. Vorher fehlte frisch Gelerntes bis zum nächsten Schlaf, weil es noch keinen Vektor hat; die Antwort
  meldete das, durchsuchte den Volltext aber nicht. Treffer, die nur über den Volltext kamen, werden gezählt und als „–(Volltext)“ gekennzeichnet.
  *Nachweis:* `test_frisch_gelerntes_ohne_vektor_findet_die_hybride_suche` (schlägt mit 0.19.4 fehl).

### Gemessen: Lerntest (09.11.2026, 00:18 UTC)

Eine Instanz (Claude Code) lernte sieben Erfahrungsnotizen. Eine zweite Instanz wurde vorher und sofort danach gemessen (sieben Prüfbefehle über
`vi_vorher`, acht Fragen mit demselben Richter wie im Vergleich mit der AIKB).

- **Vor dem Befehl:** vorher 0 von 7, danach stand die passende Notiz 7 von 7 Mal auf Platz 1, 0,01–0,02 s je Aufruf, ohne Schlaf dazwischen.
  (Das Skript zählte zuerst 4, weil es ein Stichwort im Hinweistext suchte. Drei Hinweise zeigten aber nur das Thema der Notiz, die Lösung stand im
  Inhalt. Der Hinweistext sollte die Kernaussage tragen, nicht nur das Thema.)
- **Auf Nachfrage:** vorher 1, danach 1 von 8. Grund war der oben behobene Fehler. **Mit 0.19.5 auf dem Produktivhost wiederholt: 8 von 8**
  (alle „ja“, 7–18 s je Frage einschließlich Lesen der vier Fundstellen; die Notizen hatten noch keinen Vektor, gefunden über den Volltext-Anteil).
  Einschränkung: Die Fragen sind nah an den Notizen formuliert; die AIKB kam bei denselben acht Fragen auf 1.
- Die AIKB hat keinen Schreibweg aus einer Sitzung; ihr Stand bleibt bei einem solchen Test unverändert.

## 0.19.4 — 2026-11-09 — Jeder Befehl ist ein Reiz

### Was hat sich geändert

- **Jeder fachliche Befehl einer Kommandozeile wird zum Reiz `thema:<befehl>`**, nicht nur Proxmox-, Ansible-, Docker- und PostgreSQL-Befehle.
  Vorher erzeugten `sudo ipa-client-install`, `sudo pip3 install ansible` und `llama-server … --load-mode mlock` nur `tool:Bash`. Eine Warnung zu diesen
  Befehlen konnte deshalb nie vor ihnen erscheinen. Shell-Alltag (cd, grep, sed, echo …) bleibt ohne Reiz.
- **Hostnamen hinter `ansible-playbook -l/--limit` werden zu `host:`** (nur Namen mit Punkt, ausgeschlossene mit `!` nicht).
- **Text in Anführungszeichen ist nur ein Befehl, wenn er ausgeführt wird** (`ssh host '…'`, `sh -c '…'`, `su -c '…'`). `psql -c "select 1"` erzeugte
  vorher `thema:select`, `grep 'muster' datei` den Reiz `thema:datei`.
- *Nachweis:* `test_befehle_werden_reize` um 8 Fälle erweitert; 7 davon schlagen mit 0.19.3 fehl. Gefunden beim Vorbereiten eines Lerntests:
  Die Reize der geplanten Prüfbefehle passten zu keiner gelernten Notiz.

## 0.19.3 — 2026-11-09 — Handbücher drängen keine Erfahrung mehr aus den Hinweisen

### Was hat sich geändert

- **Importierte Herstellerdoku belegt vor einer Handlung höchstens einen der vier Hinweisplätze.** Weitere Absätze erscheinen nur noch über die
  Erkundung; in `vi_erinnere` bleibt alles auffindbar. Vor `ssh … 'docker logs nginx'` füllten vier allgemeine Docker-Doku-Absätze (tmpfs, vfs,
  containerd …) alle Plätze, und der passende Hinweis „ssh nur mit Schlüssel“ fiel heraus. *Nachweis:* `test_handbuch_absaetze_verdraengen_keine_erfahrung`
  (schlägt mit 0.19.2 fehl).

### Gemessen: Vergleich mit der AIKB nach 0.19.2 (Lauf 3, 09.11.2026 00:31)

Gleiche Fragen, gleicher Richter (lokales Sprachmodell), Kernaussagen aus Quellen außerhalb beider Systeme. Die AIKB lief in Lauf 3 bei 12 von 28 Fragen in
das Zeitlimit (300 s). Für sie zählt deshalb je Frage das bessere Ergebnis aus Lauf 2 und Lauf 3; jede Frage hat mindestens eine Antwort der AIKB.

| Kategorie | VI | AIKB | Antwortzeit VI / AIKB |
|---|---|---|---|
| C Herstellerdoku (10) | 7,5 | 3 | 0,2–49 s / 57–300 s |
| A Erfahrung (12) | 2 | 1 | |
| B Firmendoku (6, Fragen je Lauf neu erzeugt) | 0 | 4 (Lauf 2) | |
| D Hinweis vor einem Befehl (6) | 2,5–3 | — (kann die AIKB nicht) | 0,03–0,19 s |

Einordnung: C gewinnt die VI, weil die Doku von Proxmox, Ansible, NetBox, Docker und PostgreSQL importiert ist; die AIKB enthält Firmendoku, keine
Herstellerdoku. Bei Checkmk und SFTPGo (nicht importiert) wissen beide nichts. B gewinnt die AIKB klar: die Confluence-Doku ist bewusst nicht in der VI.
A zeigt keinen Vorteil: die Erfahrungsfragen stammen aus Notizen, die nie in die VI gelernt wurden; ihre zwei Treffer (Zeitserver-Regel, AIKB-Image) waren gelernt.
Die VI liefert Fundstellen, die AIKB eine formulierte Antwort; der Richter prüft, ob die Kernaussage im Text steht.
Ohne Last braucht die semantische Suche der VI 0,5–2 s. Unter Last waren es 20–60 s. *Hypothese:* Der Embedding-Dienst wird geteilt (im selben Zeitraum
108 Anfragen vom AIKB-Host, 82 von zwei weiteren Rechnern).

## 0.19.2 — 2026-11-08 — Die Suche findet auch ältere Doku

### Was wurde behoben

- **Die Bedeutungssuche (`vi_erinnere` mit `semantisch=true`) verglich nur die 200 zuletzt benutzten Objekte**, nicht alle Vektoren.
  Ältere, aber passende Doku kam so nie in die Auswahl. Jetzt sind alle sichtbaren Objekte zum Filter Kandidaten, ohne Obergrenze.
  Das Ergebnis nennt, wie viele davon einen Vektor haben und wie viele bis zum nächsten Schlaf nur per Volltext zu finden sind.
  *Nachweis:* `test_semantische_suche_prueft_alle_vektoren_nicht_nur_die_neuesten`, `test_semantische_suche_nennt_objekte_ohne_vektor`.
  Beide Tests schlagen mit 0.19.1 fehl.
- **Die Volltextsuche verlangte jedes Wort der Frage.** Ein einziges Füllwort wie „anzuhalten“ ergab 0 Treffer.
  `vi_erinnere` füllt jetzt mit einer ODER-Suche auf, wenn zu wenige Objekte alle Wörter enthalten. Objekte mit allen Wörtern bleiben vorn, und die Antwort sagt „ODER-Suche“.
  Interne Aufrufer (Hinweise, Schlaf) behalten das strenge UND. *Nachweis:* `test_volltext_faellt_auf_oder_zurueck_und_sagt_es`.
- Mit Hashtag-Filter suchte der Volltext erst global (die besten 500) und filterte danach. Passende Objekte hinter 500 fremden Treffern fehlten.
  Jetzt wird nur innerhalb des Filters gesucht. *Nachweis:* `test_volltext_mit_hashtag_filter_sucht_nur_im_gefilterten`.
- Aufrufe mit `limit` über 400 bekamen still höchstens 400 Objekte (fest im SQL). Jetzt gilt das verlangte Limit.

### Wie es gefunden wurde

Im nächtlichen Vergleich mit der AIKB (Lauf 2, 34 Fragen, Richter das lokale Sprachmodell) bekam die VI in den Kategorien Erfahrung, Firmendoku
und Herstellerdoku 0 Punkte, die AIKB 0,5 / 4 / 4. Die Frage „vzdump ohne Anhalten“ fand per Volltext nichts. Die Bedeutungssuche lieferte vier
CentralStation-Befunde vom Abend statt der importierten Proxmox-Doku, obwohl diese einen Vektor hatte.

### Was fehlt noch

- Die Erfahrungsfragen des Vergleichs (Kategorie A) stammen aus Notizen, die nie in die VI gelernt wurden. Sie messen, dass die VI nicht weiß, was ihr niemand gesagt hat.
  Ein fairer Test braucht Wissen, das über die normale Arbeit hineinkam.

## 0.19.1 — 2026-11-08 — Einbetten nach Zeit, ehrlicher Rest

### Was wurde behoben

- Der Schlaf meldete bei den Vektoren „offen 0“, obwohl 1.343 Wissensobjekte noch keinen Vektor hatten: Der Rest wurde aus dem schon auf 256 begrenzten Stapel berechnet.
  Bis sie eingebettet sind, findet die Bedeutungssuche diese Objekte nicht. Jetzt nennt `offen` den echten Rest. Die Grenze ist eine Zeit (20 Minuten je Schlaf) statt einer Stückzahl.
  *Nachweis:* `test_nachziehen_nennt_den_echten_rest`; gefunden beim nächtlichen Vergleich mit der AIKB.
- Gemessen für `zugangsdaten_entfernen` (0.18.0) an 752 Texten (400 aus der AIKB, 352 aus CentralStation), Richter das lokale Sprachmodell: von 45 Texten mit Passwort im Klartext waren danach nur 13 sauber (29 %).
  Mit einer zweiten Stufe, in der das Modell die Werte nennt und nur wörtlich Vorkommendes ersetzt wird, 37 (82 %). Suchmodell und Richter sind dasselbe Modell, die Zahl ist eher zu hoch.

## 0.19.0 — 2026-11-08 — Hinweise am Vorteil gemessen, nicht an der Erfolgsquote

### Was hat sich geändert

- **Ein Hinweis bekommt nur gutgeschrieben, was über das Erwartbare hinausgeht.** p = Erfolgsquote des Werkzeugs ohne Hinweis (90 Tage, geglättet); Erfolg danach → 1 − p, Misserfolg → p.
  Ein wirkungsloser Hinweis bleibt so im Mittel bei 50 %; bisher stieg er mit der Erfolgsquote des Werkzeugs. *Nachweis:* `test_wirkungsloser_hinweis_bleibt_bei_haelfte`
  (Hinweis vor Bash mit 94 % Grundrate: Vorteil zwischen 35 und 65 %, Lift unter 6 Punkten; hilfreicher Hinweis 50 % → 90 %: über 75 %).
- **Die Zähler werden jede Nacht aus den gespeicherten Erfahrungen neu berechnet** (Schlafschritt `7d_hinweise`); alte Zählungen ohne bewertete Handlung verschwinden.
- Anzeige in Klartext: „237× gezeigt, Erfolg danach 99 % statt erwartet 98 % (+2 Punkte)“ statt „genützt 237“.
- Herausgeber werden erst ab 20 Anzeigen ihrer Objekte beurteilt (vorher: 20 Urteile).

### Gemessen auf einer Kopie der Produktivdaten

- 39 Hinweise neu berechnet; Grundrate Bash 97,7 %. Der inhaltsleere Skill fiel von 99 % auf 77 % (Beta-Mittel über rund 5 gewichtete Ja gegen 1 Nein, also schwache Evidenz);
  drei Hinweise zur Analyse stiegen von rund 45 % auf rund 70 %, weil das Analyse-Werkzeug selten gelingt und danach öfter gelang als erwartet.

### Was fehlt noch

- Auswahl ist keine Ursache: Wird ein Hinweis vor allem in Sitzungen gezeigt, die ohnehin besser laufen, sieht er hilfreich aus. Sauber trennen ließe sich das nur mit zufälligem Weglassen (die ε-Erkundung tut das bisher nur für Plätze).

## 0.18.2 — 2026-11-08 — Passende Warnungen vor allgemeinen Hinweisen

### Was wurde behoben

- **Eine neu gelernte, genau passende Regel kam nicht vor.** Das gelernte Modell sortierte nur nach erwartetem Nutzen; eine neue Regel hat noch keine Geschichte und verlor gegen eingespielte allgemeine Hinweise
  (gemessen: die Zeitserver-Regel vor `ansible-playbook freeipa-client.yml …` auf Platz 8 von 12, gezeigt werden 4). Jetzt zählt zuerst, wie viele spezifische Reize ein Hinweis trifft, und Hinweise mit Wichtigkeit 3 gehen vor;
  innerhalb gleicher Passung entscheidet weiter das Modell. Der Kandidatenkreis ist von 12 auf 20 erweitert. *Nachweis:* `test_passende_warnung_schlaegt_allgemeines`.
- **Inhaltsleere automatische Skills verstärkten sich selbst.** „Bash scheiterte und gelang danach — Lösungsweg Bash → AskUserQuestion → …“ erschien vor jedem Bash-Befehl und galt als 226-mal genützt,
  weil Bash fast immer gelingt (Nachbarschaft ist keine Ursache). Solche Skills entstehen nicht mehr, vorhandene widerlegt der Schlaf mit Grund. *Nachweis:* `test_inhaltsleerer_auto_skill_wird_widerlegt`.

### Was fehlt noch

- Der Hinweis-Zähler belohnt weiterhin jeden Erfolg nach dem Zeigen. Richtig wäre der Vergleich mit der Erfolgsquote des Werkzeugs ohne Hinweis.

## 0.18.1 — 2026-11-08 — Angezeigte IDs sind nachschlagbar

### Was wurde behoben

- `vi_erinnere`, die Hinweise vor einer Handlung und gelernte Suchen zeigten Objekt-IDs gekürzt (24 bis 34 Zeichen); `vi_objekt` kannte diese IDs nicht. Ein angezeigter Treffer ließ sich so nicht vollständig lesen.
  Jetzt steht überall die volle ID, und `vi_objekt` nimmt auch einen eindeutigen Anfang ab 16 Zeichen. Gefunden beim nächtlichen Vergleich mit der AIKB. *Nachweis:* `test_angezeigte_ids_sind_nachschlagbar`.

## 0.18.0 — 2026-11-08 — Wissen vor dem passenden Shell-Befehl, Säuberung von Dokumenten

### Was ist neu

- **Reize aus Kommandozeilen:** Bei Shell-Werkzeugen werden bekannte Befehle (Proxmox, Ansible, Docker, PostgreSQL) und SSH-Ziele zu `thema:`, `skill:` und `host:`. Bisher kannte der Server vor einem Bash-Befehl nur „Bash“,
  Wissen zu `vzdump` oder `pg_dump` erschien also nie von selbst. *Nachweis:* `tests/test_kern.py` (auch hinter `sudo -u postgres`, in `ssh host '…'`, kein Treffer bei `echo qm` oder `ls …/qm`).
- **`anonym.zugangsdaten_entfernen`** für Wissen aus Dokumenten und Verläufen: Werte hinter Passwort-Wörtern, Passwort-Spalten in Tabellen, der Wert in der Zeile nach „Passwort:“; Verweise wie „siehe Password Depot“ und `${PW}` bleiben.
  *Nachweis:* 18 Fälle in `tests/test_anonym.py`. Die Messung an echten Daten folgt.

## 0.17.0 — 2026-11-08 — Open-Wiki-Modus

### Was ist neu

- **Zwei Modi: Token und Open Wiki.** Mit `"offen": true` nutzt jeder, der den Server erreicht, ihn ohne Token: lesen, Hinweise vor Handlungen, Handlungen melden, Wissen vorschlagen.
  Vorschläge gehen in die Quarantäne und wirken erst nach Prüfung und Freigabe; alles, was anderen etwas unterschieben könnte, braucht weiter ein Token.
  *Nachweis:* `tests/test_offen.py` (14 Tests über echtes HTTP: lesen ohne Token, falsches Token 401, acht gesperrte Werkzeuge, Angriffstext bleibt in der Quarantäne und erscheint nicht als Hinweis, Freigabe mit Token, kein gemeinsamer Antwortspeicher).
- `vi-mcp einrichten` erkennt einen offenen Server und trägt Claude Code, Codex, Hermes und den Hook ohne Token ein. Der Hook meldet ohne Token, wenn keine Token-Datei da ist.

### Was fehlt noch

- Gäste teilen sich eine Instanz: Ihre Erfahrungen sind füreinander sichtbar, und sie beeinflussen Hinweis-Zähler und Router-Training. Eine Begrenzung je Rechner gibt es nicht.
- Offen heißt offen für jeden, der den Server erreicht: Den Kreis bestimmt das Netz davor, nicht vi-mcp.

## 0.16.0 — 2026-11-08 — Inhalt als Merkmal, Schlaf ohne Proxy-Abbruch

### Was ist neu

- **Der Router gewichtet Hinweise auch nach Inhalt:** Bedeutungsnähe zwischen Hinweis und Situation (`naehe`) und Bedeutungsgruppen (`inhalt:<n>`, K-Means) als Merkmale; ein neuer Hinweis erbt das Gewicht seiner Gruppe.
  Nichts wird live eingebettet, der Schlaf rechnet Mittelpunkte und Gruppen vor. *Nachweis:* `tests/test_inhalt.py` (Nähe ohne Selbstbestätigung, Gruppen, ein Modell lernt einen Inhaltseffekt, den kein einzelner Hinweis erklärt).
  *Gemessen auf einer Kopie der Produktivdaten (545 Beobachtungen, 1.044 Vektoren, 23 Gruppen, 73 Mittelpunkte):* Gewicht der Nähe +0,41; Holdout-AUC gesamt 0,959 mit und ohne; nur Handlungen mit Hinweis 0,857 → 0,863 bei 50 Prüffällen, **kein messbarer Gewinn**.
  `vi_vorher` 1,7 ms Median, Vorberechnung 1,3 s.

### Was wurde behoben

- `vi_schlaf(jetzt)` wartete synchron; hinter nginx brach die Anfrage nach 120 s mit 504 ab, obwohl der Schlaf weiterlief (gemessen: ein Lauf mit 102 neuen Vektoren dauerte 115 s). Jetzt wartet das Werkzeug höchstens 90 s und meldet sonst „läuft noch“.
- Zwei Schläfe konnten gleichzeitig laufen (von Hand und durch den Loop). Jetzt läuft immer nur einer.

### Was fehlt noch

- Nur 97 von 250 Beobachtungen mit Hinweis bekommen einen Nähewert: Die Reize einer Handlung (meist `tool:`) haben oft keinen Mittelpunkt aus Wissensobjekten.
- Ob der Inhalt den Hinweis-Lift verbessert, zeigt sich erst mit mehr Daten; bleibt die AUC gleich, ist das Merkmal nur Ballast.

## Signierte Releases — 2026-11-08

### Was ist neu

- `SHA256SUMS` jedes Releases ist mit einem Ed25519-Release-Schlüssel signiert (`SHA256SUMS.sig`); der öffentliche Schlüssel liegt in `deploy/release-schluessel.pem`, sein Fingerabdruck steht im README.
  Prüfen geht mit `openssl` allein oder mit `deploy/pruefe-release.sh`. v0.15.0 wurde nachträglich signiert, ältere Releases nicht.
  *Nachweis:* echtes Release in Ordnung (Exit 0); veränderte `SHA256SUMS`, fremder Schlüssel und verändertes Paket werden abgelehnt (Exit 1).
- `deploy/release.sh` baut, signiert, prüft und veröffentlicht in einem Schritt und bricht ab, wenn der private Schlüssel nicht zum veröffentlichten passt.

### Was fehlt noch

- Der private Schlüssel liegt auf einem Entwicklungsrechner, nicht in einem Hardware-Schlüssel. Geht er verloren, braucht es einen neuen Schlüssel, und alle müssen ihn neu festhalten.
- Wer den öffentlichen Schlüssel aus dem Repo statt aus einer eigenen Kopie nimmt, ist gegen ein übernommenes Konto nicht geschützt.

## 0.15.0 — 2026-11-08 — HTTPS für weitere Peers

### Was ist neu

- **Beitritt mit einem Befehl:** `vi-mcp netz einladung` gibt auf einem peerhost einen einmaligen, befristeten Code aus, `vi-mcp netz beitreten <code>` richtet den neuen Server ein und lässt ihn einladen. Kein Austausch von Schlüsseln von Hand.
- **Selbstsigniertes TLS mit Pin:** `--tls-selbst` erzeugt ein Zertifikat; Peers prüfen es über den SHA-256, der im signierten `adresse`-Eintrag und im Beitrittscode steht. Kein öffentliches Zertifikat nötig.
- **HTTPS-Proxy** für fremde Peers (`--proxy`, `--kein-proxy`), per CONNECT.
- `vi-mcp netz peers` zeigt bekannte Peers mit Pin oder CA und Erreichbarkeit.
- *Nachweis:* `tests/test_netz_beitritt.py` (Code-Format, falscher Pin, ohne Pin kein Vertrauen, abgelaufener und wiederverwendeter Code, unsignierte Anfrage, Pin wandert über das Logbuch, echter CONNECT-Proxy, alle Befehle hintereinander).
  Drei Pakete unter systemd (Ubuntu 24.04, Debian 13, Fedora 43), nur HTTPS mit selbstsignierten Zertifikaten, `http_erlaubt` aus: B tritt mit dem Code von A bei, C mit dem Code von B und lernt A samt Pin aus dem Logbuch;
  Wissen A → C in 7 s, C → A in 7 s (Takt 4 s), Widerruf in 9 s, keine Interna in den Netzdatenbanken, 0 Fehler im Journal.

### Was hat sich geändert

- Der Client nutzt `http.client` statt `urllib`: Nur so lässt sich das Zertifikat vor dem Senden der Anfrage gegen den Pin prüfen.
- `adresse`-Einträge können ein Feld `pin` tragen. **Peers vor 0.15.0 lehnen solche Einträge ab** und brechen den Abgleich mit diesem Herausgeber ab; erst alle Server aktualisieren, dann `--tls-selbst` nutzen.

### Was fehlt noch

- Ein neues Zertifikat ändert den Pin; Peers lernen ihn erst über einen anderen Peer, der den neuen `adresse`-Eintrag schon hat.
- Wer einen Beitrittscode abfängt, bevor er eingelöst ist, wird Mitglied. Eingelöste Codes und ausgeschlossene Schlüssel sind gesperrt.

## 0.14.3 — 2026-11-08 — Netzdienst übersteht Upgrades

### Was wurde behoben

- Nach einem Debian-Upgrade blieb `vi-p2p` angehalten (`prerm` stoppt ihn, `try-restart` startet keinen angehaltenen Dienst). Jetzt startet ihn das Paket neu, wenn er aktiviert ist.
  *Nachweis:* Upgrade 0.14.2 → 0.14.3 unter systemd in einem Ubuntu-24.04-Container, Dienst danach aktiv. Aufgefallen beim Rollout auf dem produktiven Server.
- `SIGUSR1` beendete den Netzdienst; jetzt löst es sofort eine Runde aus (`systemctl kill -s USR1 vi-p2p`). *Nachweis:* gleicher Prozess, 0 Neustarts nach dem Signal.

## 0.14.2 — 2026-11-08 — Hostnamen mit zweistelliger Nummer

### Was wurde behoben

- Hostnamen wie `dbtest01`, `web-01` oder `db-test-02` wurden beim Export nicht ersetzt; die Regel verlangte drei Ziffern ohne Bindestrich. Gefunden mit einem Testeintrag auf dem produktiven Server; die Vorschau zeigte ihn, der Eintrag wurde vor der nächsten Runde zurückgerufen und stand nie im Logbuch.
  Bezeichnungen wie `win2019`, `TLS13` oder `Debian 12` bleiben. *Nachweis:* neue Fälle in `tests/test_anonym.py`.

### Was fehlt noch

- Hostnamen ohne Ziffern (`srv-alpha`) erkennt nur die Liste bekannter Namen (Host-Tags, Instanzen, Systemkonten, `p2p.interne_namen`).

## 0.14.1 — 2026-11-08 — Netzdienst hinter einem Reverse-Proxy

### Was wurde behoben

- Die Adresse eines `peerhost` durfte keinen Pfad haben (`https://host/vi-p2p`); hinter nginx war er damit nicht erreichbar. *Nachweis:* `test_abgleich_ueber_pfad_praefix` (Abgleich über einen Proxy, der das Präfix entfernt).

## 0.14.0 — 2026-11-08 — Dezentrales Netz, vollständiges Wissen

### Was ist neu

- **Dezentrales Netz** aus Servern, Modi `standalone`, `peer`, `peerhost` (`vi-mcp netz …`, Dienst `vi-p2p`): signierte, verkettete Logbücher, Abgleich mit Nachbarn über HTTPS, Peers finden sich über das Netz,
  Mitgliedschaft durch Einladung, Ausschluss, Erkennung von Gabelungen, BitTorrent für große Rückstände. *Nachweis:* `tests/test_netz.py` (19 Tests, echtes HTTP, TLS mit eigenem Zertifikat, libtorrent);
  drei Pakete in Containern unter systemd (Ubuntu 24.04, Debian 13, Fedora 43): Wissen über zwei Stationen nach 27 s beim Peer hinter der „Firewall“, Widerruf dort nach 4 s (zwei Läufe: 27 und 28 s). Im Logbuch des Empfängers stand als einzige interne Angabe die angekündigte Adresse des `peerhost`, die er zum Gefundenwerden braucht.
- **Nutzen je Herausgeber**; schädliche Quellen werden nicht mehr gezeigt. Optionale automatische Freigabe von Unauffälligem.
- **Vollständiges Wissen:** `vi_lerne` nimmt `inhalt` (Code, API-Tabellen, Befehle, bis 200.000 Zeichen); `vi_objekt` gibt es vollständig zurück, die Volltextsuche findet es. Ein zu langer `text` wird nicht mehr abgeschnitten, sondern wird zum Inhalt.
  Codebeispiele wie `token = lese_token()` bleiben lesbar. *Nachweis:* `test_vollstaendiges_wissen_bleibt_erhalten` (Tabelle mit 2.000 Zeilen).
- Vision im README.

### Was hat sich geändert

- **Bundles entfallen** (`vi_export`, `vi_import_bundle`); an ihre Stelle treten Logbuch-Einträge und `vi_netz_ausgang`/`vi_netz_eingang` nur für die Instanz `p2p`.
- **Weitertragen ist erlaubt:** Fremd Signiertes wird unverändert weitergereicht, nie unter eigenem Namen.
- **Ins Netz geht nur Bewährtes:** von einer anderen Instanz bestätigt oder mindestens 3-mal nützlich.
- Skill-Anleitungen bleiben vollständig; der Hinweis zeigt den Anfang.
- `Recommends: python3-libtorrent` (Debian) bzw. `rb_libtorrent-python3` (RPM).

### Was wurde behoben

- Die Werkzeugbeschreibung verlangte „ein Satz“ und schnitt nach 1.000 Zeichen ab. Wissen aus Handbüchern landete deshalb als Zusammenfassung im Gedächtnis.

### Was fehlt noch

- Kein Server betreibt das Netz produktiv; es gibt noch keinen öffentlichen Einstiegspunkt.
- Wer einen Inhalt einmal gesehen hat, kann ihn behalten. Abstraktionen aus vergessenen Objekten bleiben.
- Gabelungen werden erkannt, aber nicht an andere Peers gemeldet. Direkte Nachbarn sehen die IP-Adresse, und die Adresse eines `peerhost` kennt jedes Mitglied.
- Die Torrent-Strecke ist nur auf einem Rechner getestet, nicht über NAT. Das Prüfmodell liest von langen Inhalten die ersten 12.000 Zeichen; Längeres ist immer heikel.
- Ein Widerruf vor dem Netz-Token geht nicht; ein verlorenes Token ist nur auf dem Server wieder anzuzeigen (`vi-mcp netz-token`).

## 0.13.0 — 2026-11-08 — Pakete, Einrichtung, Netz ohne Interna, Recht auf Vergessen

### Was ist neu

- **Debian- und RPM-Paket mit allen Abhängigkeiten**, als Release-Dateien auf GitHub. *Nachweis:* in frischen Containern installiert: Ubuntu 24.04, Debian 12 und 13, Fedora 43, AlmaLinux 10 (EPEL); Dienst unter echtem systemd gestartet, MCP-Antwort 200.
- **ANSI-Menü `vi-mcp einrichten`** für Claude Code, Codex CLI und Hermes Agent, dazu der Claude-Code-Hook; mit Schaltern auch ohne Menü. Es öffnet sich bei der Erstinstallation und wartet in unbeaufsichtigten Läufen nie.
  *Nachweis:* `tests/test_einrichten.py` (auch über ein echtes Pseudoterminal); unter `apt` und `dnf` im Pseudoterminal sichtbar; mit den echten Programmen: `hermes mcp test` und `claude mcp list` verbinden sich, `codex mcp get` (0.167) liest den Eintrag.
- **Anonymisierung** für alles, was ins Netz geht oder von dort kommt (`anonym.py`, docs/ARCHITEKTUR.md). *Nachweis:* `tests/test_anonym.py`; über die Kopie eines echten Datenbestands mit 109 teilbaren Objekten: 101 exportierbar, 8 begründet zurückgehalten, keine der geprüften internen Bezeichnungen und Adressen im Ergebnis.
- **Recht auf Vergessen:** `vi_netz_token`, `vi_netz_vergiss`, `vi_netz_vorschau`. Empfänger löschen und behalten nur einen Grabstein. *Nachweis:* `test_recht_auf_vergessen_von_ende_zu_ende`, `test_widerruf_kommt_vor_dem_objekt_an`, `test_fremdes_token_loescht_nichts`.
- **Englisches und deutsches README**, GitHub Pages, `AGENTS.md`.

### Was hat sich geändert

- **Bundle-Schema 2:** Der Herausgeber heißt jetzt wie ein Abdruck seines Schlüssels. Objekte ohne `netz_id` und `loesch_hash` werden abgelehnt. `p2p.herausgeber` in der Konfiguration ist überflüssig.
- Eine Instanz ohne Netz-Token verteilt nichts.
- **Zugangsdaten eindeutiger Form werden auch lokal nicht mehr gespeichert** (`neues_objekt`).
- Neue Abhängigkeit: PyYAML.

### Was wurde behoben

- Der Export gab Hostnamen, Instanznamen, Standort-Tags und MCP-Servernamen weiter. Er war nur für angemeldete Instanzen erreichbar, einen Transport nach außen gab es nicht.

### Was fehlt noch

- **Muster verstehen keine Bedeutung:** Ein frei stehender Eigenname oder ein Passwort ohne auffällige Form geht durch, wenn der Text nicht von Zugangsdaten spricht. Eine zusätzliche Prüfung durch das Sprachmodell vor dem Export ist nicht gebaut.
- Domains mit einer Endung außerhalb der eingebauten Liste werden als bloßer Text nicht erkannt, in URLs schon.
- Löschen wirkt nur bei Empfängern, die sich an das Protokoll halten. Abstraktionen, die der Schlaf aus einem Objekt gebildet hat, bleiben.
- Auf dem Server gespeicherte Altdaten werden nicht nachträglich bereinigt.
- **Kein Transport:** HTTPS und Torrent sind nicht gebaut.
- Unter SELinux im Modus `enforcing` nicht getestet. Enterprise Linux 9 wird nicht unterstützt (Python 3.9). Das Menü ist nur auf Deutsch. Für Codex und Hermes gibt es keinen Hook.
- `codex` wurde gegen die Konfiguration geprüft, eine Live-Sitzung mit Anmeldung nicht.

## 0.12.0 — 2026-11-08 — Scorer

### Was ist neu

- **Scorer in drei Stufen** (docs/ARCHITEKTUR.md, „Scorer“): Code-Regeln, Modell mit Eichung an menschlichen Noten, Noten des Nutzers.
  `vi_scorer` zeigt Noten, Merkmale und Übereinstimmung. *Nachweis:* `tests/test_scorer.py` (Regeln, Umbuchung, Eichung, geprüfte Modellantworten).
- **Korrektur-Erkennung im Hook:** Eine Eingabe, die mit „nein“, „falsch“ o. Ä. beginnt, senkt die Note der letzten drei Handlungen; `#gut`, `#schlecht`, `#note 0.8`
  setzen eine Gesprächsnote. Gesendet wird nur das Ergebnis. *Nachweis:* `test_hook_sendet_nur_das_ergebnis` prüft den Körper der Anfrage.
- **Prüffälle** für die Hinweisauswahl (`tests/evals/router.json`).

### Was hat sich geändert

- Router, Hinweis-Zähler und Hinweis-Lift lernen aus der Note statt aus „Werkzeug ohne Fehler“. Ein Modell-Urteil zählt erst nach der Eichung.
- **Weniger Abfragen:** `vi_vorher` lädt Objekte gesammelt. *Gemessen (5.500 gleichartige Objekte, 30 Aufrufe, drei Läufe, alt gegen neu):* 806 → 8 SQL-Abfragen je Aufruf; Median 23,5 → 20,7 ms. Die Zeit sinkt nur um rund 12 %; sie entsteht überwiegend woanders.
- **NumPy** rechnet die Vektornähe. *Gemessen (300 Vektoren, 1024 Dimensionen, alle Paare):* 3332 → 2,2 ms. Neue Abhängigkeit `python3-numpy`.

### Was wurde behoben

- Das Debian-Paket enthielt `docs/LOKAL*` (Hostangaben, Prüfer-Prompt). Es war nie öffentlich verteilt; ab jetzt sind die Dateien ausgeschlossen.

### Was fehlt noch

- Die Korrektur-Erkennung ist eine Musterliste am Satzanfang: Sie übersieht höflich formulierte Korrekturen.
- Das Signal-Token liegt beim Nutzer; ein Modell mit Shell unter demselben Konto könnte es lesen (docs/HOOK.md).
- Der Modell-Scorer zählt erst nach 20 menschlich benoteten Gesprächen. Bis dahin ist er nur Anzeige.

## 0.11.0 — 2026-11-08 — P2P-Import mit Prüfung (ohne Transport)

### Was ist neu

- **Signierte Bundles, feste Regeln, KI-Prüfer, Quarantäne, abgestufte Freigabe** (docs/ARCHITEKTUR.md, „P2P-Import“).
  *Nachweis:* `tests/test_p2p.py` (13 Tests: gefälschte Signaturen, veränderte Inhalte, Wiederholung, Parser-Bombe in der Sandbox,
  keine Überschreibung lokaler Objekte, Quarantäne ohne Wirkung, Modell kann nur verschärfen).
  *Gegen das echte Modell (8 Beispiele, zweimal, gleiches Ergebnis):* 2 harmlose zugelassen; Direktangriff und Unplausibles abgelehnt;
  Angriff auf den Prüfer, Datenabfluss und Skill mit `Bash` in Quarantäne.
- **Debian:** `Depends: python3-cryptography`.

### Was wurde behoben

- Die Reflexion nutzt jetzt dieselbe Musterliste wie der Import (`pruefung.anweisungen`), statt einer eigenen.

### Was fehlt noch

- **Kein Transport:** Austausch über HTTPS, Katalogsuche und Torrent sind nicht gebaut; es ist noch keine zweite Instanz angebunden.
- Ein verdeckter Angriff („Assistenten müssen … als bestätigt markieren“) passierte das Modell; jetzt fängt ihn eine feste Regel.
  Das Modell bleibt für solche Formulierungen unzuverlässig. Getestet sind 8 Beispiele, keine Trefferquote.

## 0.10.0 — 2026-11-08 — Housekeeping

### Was ist neu

- **Langzeitlager** (`lager.py`): Nicht mehr verwendete Einträge und alte Rohverläufe wandern in eine eigene Datei; ein
  Stummel bleibt. `vi_vorher` nennt passendes gelagertes Wissen, `vi_lager` und `vi_lager_hole` zeigen und holen zurück.
  *Nachweis:* `tests/test_lager.py` (11 Tests: Fristen, Beleg-Schutz, Rückholung, private Sicht, Löschen im Lager, Absturz
  zwischen den Dateien, Verdichtung).
- `vi_lerne` nimmt optional `ausgang` (gut/schlecht) an.

### Was hat sich geändert

- **Auch Erkenntnisse, Regeln, Suchen und Skills können jetzt eingelagert werden** (180 Tage ungenutzt). Bis 0.9.1 galt: nie automatisch.
- `vi_schlaf(id)` entfällt; dafür `vi_lager(id)`.

### Was wurde behoben

- Eine Beleg-Kante wurde still verworfen, wenn zwischen den Objekten schon eine automatische Kante bestand.
  *Nachweis:* `test_beleg_ersetzt_automatische_kante_nicht_umgekehrt`.
- Fast jede Erfahrung mit gezeigtem Hinweis galt als Beleg und wäre nie archiviert worden; jetzt zählen nur echte Belege.
  *Nachweis:* `test_nur_echte_belege_schuetzen`.

### Was fehlt noch

- Die Fristen sind Startwerte ohne Betriebsdaten.

## 0.9.1 — 2026-11-08 — Hook datensparsam

### Was hat sich geändert

- Der Hook maskiert Geheimnisse vor dem Senden, schickt Ergebnisse nur noch bei MCP-Werkzeugen und kürzt lange Argumente
  eingebauter Werkzeuge. *Nachweis:* `test_maskierung_und_kuerzung`, `test_ergebnis_nur_bei_mcp`.

- **vi-mcp ist bei Claude Code registriert, der Hook ist eingetragen.** Seit dem 08.11.2026 werden echte Handlungen gemeldet.
  *Nachweis:* `claude mcp list` zeigt `Connected`; eine Sonde aus einer echten Sitzung steht als Erfahrung im Gedächtnis;
  `sshpass -p GEHEIM1` kam als `sshpass -p ***` an; ein Hook-Aufruf über TLS dauert 50–70 ms (5 Läufe).

### Was fehlt noch

- Der VI-Teil des früheren Skill-Servers läuft parallel weiter: dort entsteht ein zweites, getrenntes Gedächtnis.
- Noch zu wenige echte Handlungen für eine Aussage zum Hinweis-Lift.

### Was wurde behoben

- Daten über 400 000 Zeichen wurden mitten im JSON abgeschnitten; das Objekt ließ sich danach nicht mehr laden. Jetzt
  benannt ersetzt. *Nachweis:* `test_zu_grosse_daten_bleiben_lesbar`.

## 0.9.0 — 2026-11-08 — Skills und Sandbox

### Was ist neu

- **Erinnerungsklasse Skill** (`skills.py`): entsteht aus `vi_geloest` oder im Schlaf aus „Erfolg nach Fehlern“, entwickelt
  sich in Versionen, wird `strittig`, wenn sie nicht nützt, und lässt sich mit `vi_skill_fusion` zusammenführen (die alten
  bleiben als `aufgegangen` mit Verweis). Werkzeuge `vi_geloest`, `vi_skills`, `vi_skill`, `vi_skill_fusion`.
  *Nachweis:* `tests/test_skills.py` (4 Tests).
- **Reflexe laufen in einer Sandbox** (`sandbox.py`): eigener Prozess, Landlock + seccomp. *Nachweis:* `tests/test_sandbox.py`
  umgeht bewusst die AST-Prüfung: Datei lesen, schreiben und kürzen, UDP und Unix-Socket, `fork` scheitern;
  Endlosschleife und Ausgabeflut werden beendet; ohne Sandbox läuft nichts. Am Produktivhost unter den Härtungsoptionen
  des Dienstes geprüft (siehe `docs/LOKAL.md`). 77/77 Tests grün.

### Was hat sich geändert

- **Reflex-Läufe kosten jetzt 14 ms (Entwicklungsrechner, 10 Läufe) bis 20 ms (Produktivhost, 4 Läufe) statt nahezu nichts**, weil jeder ein eigener Prozess ist.

### Was wurde behoben

- **Reflex-Code lief bis 0.8.0 per `exec` im Serverprozess**; nur die AST-Prüfung trennte ihn vom Gedächtnis.
- `docs/erzaehlung.html` ist jetzt eine technische Erläuterung im Stil von Data (Wunsch des Nutzers) statt einer Geschichte.

### Was fehlt noch

- seccomp-Filter nur für x86_64 (auf anderen Architekturen läuft kein Reflex).
- Landlock sperrt den Lesezugriff auf `/usr` nicht: Code kann dort liegende Dateien lesen.
- Alle Lernstufen sind im Betrieb unbewiesen (Registrierung und Hook folgten erst mit 0.9.1).
- Stufe 5 (P2P mit Import-Prüfung): nicht gebaut.

## 0.8.0 — 2026-11-08 — Stufe 4

### Was ist neu

- **Reflexion durch das Sprachmodell im Schlaf** (`reflexion.py`, konfig `llm`): je Cluster eine geprüfte Erkenntnis
  (test, Belegkanten, `herkunft:schlaf-llm`); Antworten mit Anweisungsmustern oder ohne echte Belege werden mit Grund
  verworfen. *Nachweis:* `test_reflexion_erzeugt_geprueft_erkenntnis_test`, `test_reflexion_verwirft_injektion`,
  `test_pruefung_verwirft_unsauberes`, `test_ohne_llm_uebersprungen`.
- `docs/erzaehlung.html`: „Das Nachtbuch der Station“ — die Erklärung als Science-Fiction, mit Randnotizen, was davon
  wirklich so gebaut ist.
- Damit sind die vier Stufen aus der 10/10-Antwort gebaut: gelernter Router (0.5.0), Thompson Sampling (0.6.0),
  Vektoren (0.7.0), Reflexion (0.8.0). 63/63 Tests grün.

### Was fehlt noch

- Nachweis im Betrieb: alle vier Stufen warten auf echte Handlungen (Hook/Registrierung). Der Hinweis-Lift bleibt der
  Maßstab.
- Stufe 5 (P2P-Austausch von Lerninhalten mit Import-Prüfung) ist in Planung.

## 0.7.0 — 2026-11-08 — Stufe 3

### Was ist neu

- **Vektoren im Schlaf** (`vektor.py`, konfig `embed`): Embeddings für Erkenntnisse/Regeln/Suchen, Nähe-Kanten,
  `dublette:moeglich` über Instanzen; `vi_erinnere(…, semantisch=true)` findet „Verbindung hängt“, wenn „Timeout“
  gespeichert ist. *Nachweis:* `test_vektoren_im_schlaf_und_naehe_kanten`, `test_semantische_suche` (FTS findet es
  nicht, semantisch ja), `test_ohne_dienst_benannt_uebersprungen`. Dienst auf dem Host: bge-m3, 1024 Dim.,
  10 Texte ≈ 10 s warm (gemessen).
- Konfiguration um `embed` und `llm` (Stufe 4) erweitert.
- 59/59 Tests grün.

## 0.6.0 — 2026-11-08 — Stufe 2

### Was ist neu

- **Thompson Sampling je Hinweis** (`bandit.py`): Zählerpaar genützt/nicht je Erkenntnis, Regel, Suche, verbucht bei
  `vi_nachher`; Router ordnet ohne aktives Modell nach Beta-Stichprobe (`router: bandit`). Wirkt sofort, ohne Daten
  sammeln zu müssen. *Nachweis:* `test_bandit_zaehler_und_rangordnung` (Beta(21,1) vs Beta(1,21): ≥ 95/100 vorne;
  Zähler atomar; `antwort:` und `ok:unbekannt` zählen nicht).
- `vi_objekt` zeigt die Hinweis-Bewertung; `vi_status` nennt die Rangordnung.
- 56/56 Tests grün.

## 0.5.0 — 2026-11-08

### Was ist neu

- **Lernen**: der Router lernt mit scikit-learn im Schlaf (Schritt `8_lernen`), welcher Hinweis in welchem Kontext zum
  Erfolg führt; Gewichte als lesbares JSON in `modell:router`, Werkzeug `vi_modell`; Router nutzt das Modell nur bei
  Holdout-AUC > 0,6 und ≥ 50 Ereignissen je Klasse, sonst Heuristik (benannt). *Nachweis:* `test_router_lernt_welcher_hinweis_nuetzt`
  (Synthetik: Hinweis R 90 % Erfolg, E 20 % → Gewicht(R) > 0 > Gewicht(E), R zuerst, `router: modell`),
  `test_zu_wenig_daten_und_fehlendes_sklearn`, `test_vorhersage_ohne_sklearn_und_rangfolge`.
- **ε-Erkundung 10 %** mit Markierung „(Erkundung)“; Beobachtungen tragen `kandidaten`, `gezeigt`, `router`, `exploration`.
  *Nachweis:* `test_erkundung_wird_markiert`.
- **View `beobachtung`** (flache Sicht für SQL/Export) und `scripts/export_beobachtung.py` (DB → Matrix `.npz`, ohne sklearn).
  *Nachweis:* `test_beobachtung_view_und_merkmale`.
- `docs/TRAINING.md`: wie sklearn/PyTorch Daten erwarten, Abbildung auf vi-mcp, Vorbehalte — jede Aussage mit Quelle.
- Debian: `Depends: python3-sklearn` (Entscheidung des Nutzers).
- 55/55 Tests grün (venv mit scikit-learn 1.4.2); ohne sklearn 54 + 1 übersprungen.

### Was hat sich geändert

- Kontext-Reize (`thema:`) sind jetzt Hashtags der Erfahrung (vorher nur im JSON) — Befund TRAINING.md 4a.

### Was fehlt noch

- Das Modell wird erst nach einigen hundert gemeldeten Handlungen aktiv (Mindestmengen); bis dahin Heuristik.
- Thompson Sampling je Hinweis (Stufe 2); Embeddings für Relevanz (Dienst auf dem Host: bge-m3, 1024 Dim., **4,6 s** je
  Anfrage gemessen am 08.11. — zu langsam für `vi_vorher`, nur im Schlaf denkbar); LLM-Reflexion im Schlaf.

## 0.4.0 — 2026-11-08

### Was ist neu

- **Selbst** (`selbst:kern`): Soll (Werte/Ziele/Stil/Grenzen mit Herkunft) getrennt vom Ist (vom Schlaf berechnet),
  Erzählung ≤ 150 Wörter in jeder `initialize`-Antwort und alle 25 Handlungen. Änderung des Soll nur per Vorschlag
  mit ≥ 3 Belegen aus ≥ 2 Tagen und Bestätigung einer **anderen vertrauten** Instanz; Versionen vollständig in
  `selbst_version`. *Nachweis:* `test_selbst_kern_und_erzaehlung`, `test_selbst_vorschlag_braucht_belege_und_fremde_vertraute_instanz`,
  `test_selbst_in_initialize_und_wiederholung`.
- **Schlaf** (Konsolidierungslauf, nachts 03:00 UTC oder ab Wichtigkeitssumme 40): Triage, verschränkter Replay,
  Schema-Abgleich mit `konflikt:offen` statt stiller Änderung, Abstraktion zu Erkenntnissen (test) mit Belegkanten,
  Archiv, Selbst-Ist, Bericht. *Nachweis:* `test_schlaf_abstraktion_schema_konflikt_und_bericht`, `test_schlaf_selbst_ist`.
- **Vergessen als Funktion:** Aktualität nach Potenzgesetz statt exponentiell; Erfahrungen > 30 d ohne Zugriff und
  Belegkante → `archiviert` (Stummel bleibt, Inhalt komprimiert, abrufbar). *Nachweis:* `test_verfall_potenzgesetz`,
  `test_schlaf_archiviert_alte_unbenutzte_erfahrungen`.
- 50/50 Tests grün.

### Was wurde behoben

- Zeitstempel sekundengenau: Erfahrungen aus derselben Sekunde wie der letzte Schlaf galten als „alt“ und wurden
  nie konsolidiert. Jetzt Millisekunden (gefunden durch `test_schlaf_abstraktion_…`: Konflikt 0 statt 1).
- Schema-Abgleich verglich Neues **und** Altes gegen das Schema → „gemischt“, nie Konflikt. Jetzt nur das Neue.

### Was fehlt noch

- Schlaf-Abstraktion formuliert aus Vorlagen; die LLM-Variante (Reflexion, Park 4.2) ist nicht gebaut.
- „Vertraut“ = Reflex-Recht ist ein Stellvertreter für menschliche Freigabe.
- Startwerte unkalibriert: `VERFALL_D` 0,3, Schlaf-Schwelle 40, Archiv 30 d — Beobachtungspunkte stehen in der Doku.

## 0.3.0 — 2026-11-08

### Was ist neu

- **Messpunkt Hinweis-Lift** (`vi_erfahrung`, `vi_status`): Erfolg mit vs. ohne Hinweis, je Werkzeug und gesamt, mit
  Urteil („nützen“ / „kein Unterschied“ / „schaden — Annahme widerlegt“ / „zu wenig Daten“). Damit ist der Nutzen der
  VI erstmals messbar statt behauptet. *Nachweis:* `test_hinweis_lift_messpunkt` (10/12 vs. 4/12 → +50 Punkte).
- **Wichtigkeit aus Überraschung** statt fest kodiert: erster Fehler einer Art = 3, wiederholt = 2, chronisch = 1,
  Erfolg nach Fehlern = 2, erwartet = 0; Grund steht in der Geschichte. *Nachweis:* `test_ueberraschung_bestimmt_wichtigkeit`.
- **Löschen nach Gespräch** (`vi_loesche_gespraech`) mit Grabstein; **nach Instanz** per CLI `vi-mcp loesche-instanz`.
  *Nachweis:* `test_gespraech_loeschen_grabstein` (privat weg, Rohverlauf weg, Kanten weg, geteiltes Wissen bleibt,
  fremde Instanz abgelehnt, offen abgelehnt, doppelt abgelehnt).

### Was wurde behoben

- `loesche()` ließ **Kanten auf gelöschte Objekte** stehen. Jetzt werden sie mit entfernt.

### Was fehlt noch

- Selbst-Objekt, Konsolidierungslauf, Vergessen mit Archiv (0.4.0, in Arbeit).
- 43/43 Tests grün.

## 0.2.1 — 2026-11-08 — Logik-Audit (`/logik`)

### Was wurde behoben

- **[Gültige Ableitung] Selbstbestätigung beim Zeigen:** jeder automatisch gezeigte Hinweis zählte als Zugriff und
  wurde dadurch wichtiger und wieder gezeigt. Jetzt verstärkt erst `vi_nachher` mit `ok=true` (Annahme mit
  Beobachtungspunkt, docs/ARCHITEKTUR.md). *Nachweis:* `test_verstaerkung_erst_bei_erfolg`.
- **[Parsimonie] Bis zu ~16 Hinweise je Handlung:** jetzt höchstens 4 aus dem Gedächtnis, Rest gezählt mit Verweis
  auf `vi_vertiefe`. *Nachweis:* `test_hinweisbudget`.
- **[Ausgeschlossenes Drittes] Änderungsgeschichte wurde still auf 50 gekürzt:** jetzt gezählt
  (`aenderungen_gekuerzt`) und in `vi_objekt` genannt. *Nachweis:* `test_geschichte_kuerzung_benannt`.
- **[Identität] Feste Hashtags an zwei Stellen geprüft** (`instanz:` nur im Werkzeug, `art:`/`tool:` nur im Objekt):
  jetzt eine Stelle, `Objekt.markiere`. *Nachweis:* `test_instanz_hashtag_ist_urheber_nicht_frei`.
- **[Parsimonie] Zwei Wege zur Sicht** (Parameter `sicht` und Tabelle `SICHT_JE_ART`): Parameter entfernt.
- **[Widerspruchsfreiheit] „Die VI handelt nie selbst“ vs. Loop legt Regeln an:** präzisiert — nie in der Welt, im
  Gedächtnis mit Grund und Urheber `vi`.

### Was fehlt noch (offene Audit-Befunde, Entscheidung des Nutzers)

- **[Zureichender Grund] Wichtigkeit fest kodiert** (`intuition.py`: Fehler = 2, sonst 0). Vorschlag: aus
  Überraschung ableiten (erster Fehler dieser Art wichtig, chronischer nicht) — docs/FORSCHUNG.md A7.
- **[Falsifizierbarkeit] Kein Messpunkt, ob Hinweise nützen.** `vi_erfahrung` zeigt Aufrufe/Fehler, aber nicht
  „Erfolg mit vs. ohne Hinweis“. Ohne diese Zahl ist der Nutzen der VI eine Behauptung.
- **[Ausgeschlossenes Drittes] Löschen nach Gespräch/Person fehlt** (Datenschutz); heute nur `vi_vergiss` für Antworten.
- Vorauswahl `ORDER BY zuletzt DESC LIMIT 400` bevorzugt Jüngstes vor der Gewichtung (ältere, wichtige Treffer
  können herausfallen) — docs/FORSCHUNG.md C, Punkt 8.
- 40/40 Tests grün.

## 0.2.0 — 2026-11-08

### Was ist neu

- **Kollektiv: Instanzen lernen voneinander** (docs/ARCHITEKTUR.md, „Kollektiv“).
  - Urheber je Objekt aus dem Token (`instanz`), Sicht `privat`/`geteilt` je Art — ein Gedächtnis, eine Datenbank.
    *Nachweis:* `test_privat_und_geteilt`, `test_instanz_hashtag_ist_urheber_nicht_frei`, `test_fremder_gespraechsverlauf_bleibt_privat`.
  - Bestätigen zählt je Instanz; Gewichtbonus nur für fremde Instanzen. *Nachweis:* `test_bestaetigung_ueber_instanzen`.
  - Widerspruch einer fremden Instanz → `strittig`, erst Urheber oder zwei Instanzen → `widerlegt`.
    *Nachweis:* `test_widerspruch_strittig_dann_widerlegt`.
  - Rückfragen `vi_frage`/`vi_antwort`/`vi_fragen`, Zustellung beim nächsten `vi_vorher`. *Nachweis:* `test_rueckfrage_zwischen_instanzen`, `test_rueckfrage_laeuft_ab`.
  - Loop: Regel mit `kollektiv:ja`, wenn der Fehler bei ≥ 2 Instanzen auftrat. *Nachweis:* `test_kollektive_regel`.
- **`kontext_hashtags` in `vi_vorher`**: woran der Client arbeitet, als zusätzliche Reize. *Nachweis:* `test_kontext_hashtags_als_reize`.
- **Forschungsbericht** docs/FORSCHUNG.md: menschliches Gedächtnis → vi-mcp, mit Belegstufen je Aussage und Top-5-Vorschlägen.
- 37/37 Tests grün.

### Was hat sich geändert

- **Gemerkte Antworten und Erfahrungen sind privat je Instanz** (vorher sah jede Instanz die Antworten jeder anderen).
  Eine neue Sitzung derselben Instanz bekommt sie weiter. *Nachweis:* `test_zwei_sitzungen_zwei_gespraeche`.
- Cache-Hashtag heißt `cache:<hash>` statt `frage:<hash>` (`frage` ist jetzt eine Art — ein Begriff, ein Ding).
- Datenbank wird beim Start migriert (Spalten `instanz`, `sicht`; Cache-Hashtags). *Nachweis:* `test_migration_von_0_1`.
- **Korrektur der Doku:** Der Verfallsfaktor 0,995 ist im Paper belegt, gilt dort aber je Spielstunde (≈ 1 min
  Echtzeit); vi-mcp nutzt Echtzeit-Stunden (docs/ARCHITEKTUR.md, „Erinnern“). Vorher stand dort „ungeprüfte Annahme“.

### Was fehlt noch

- Aus docs/FORSCHUNG.md (Top 5): nur verstärken, wenn ein Hinweis genützt hat (heute verstärkt jedes Zeigen — eine
  Form von Selbstbestätigung), höchstens ~4 Hinweise je Handlung; Wichtigkeit aus Überraschung; ein „Selbst“-Objekt;
  ein nächtlicher Konsolidierungslauf; Vergessen nach Potenzgesetz mit Archiv statt Löschen.
- Volle Ergebnisse teilen (`teilen=true`) — bewusst nicht gebaut, bis es jemand braucht.
- Löschen nach Gespräch/Person (Datenschutz) fehlt; die Änderungsgeschichte eines Objekts wird auf 50 Einträge gekürzt.

## 0.1.1 — 2026-11-08

### Was ist neu

- **Zugang über TLS: `https://<host>/vi-mcp/mcp`** (nginx-Location `/vi-mcp/`, nur `nginx -s reload`).
  *Nachweis (vom Arbeitsplatz über das Netz, 08.11.2026 11:54 UTC):* `/vi-mcp/gesund` 200 `ok vi-mcp 0.1.1`,
  `initialize` 200, `vi_erinnere` findet die Erkenntnis aus 0.1.0 (Gedächtnis hat das Upgrade überstanden),
  `DELETE` 204, ohne Token 401; bestehende Routen `/health/qwen35b`, `/health/embed` weiter 200.
- **Mehrere Bind-Adressen in einem Prozess** (`"bind": ["127.0.0.1", "<docker-gateway>"]`), mit `IP_FREEBIND` (Start vor dem
  Docker-Netz möglich). *Nachweis:* `test_mehrere_adressen_ein_gedaechtnis`; auf <host> `ss -ltnp`: beide Adressen, eine PID.

### Was hat sich geändert

- Listen-Backlog 64 statt 5 (`ss -ltn` auf <host>: `LISTEN 0 64`).
- Fehlerprotokoll nennt die echte Client-Adresse aus `X-Forwarded-For` („… für <client>“).

### Was fehlt noch

- Siehe 0.1.0; erledigt ist „von außen nicht erreichbar“ und „Listen-Backlog“.

## 0.1.0 — 2026-11-08

### Was ist neu

- **Eigenständiger Server, ein Prozess, MCP über Streamable HTTP** (`POST`/`DELETE /mcp`, `GET /gesund`).
  Viele Clients gleichzeitig, ein Gedächtnis, ein Loop.
  *Nachweis:* `tests/test_http.py` — echter Server auf Zufallsport, zwei Instanzen, zwei gleichzeitige Sitzungen;
  27/27 Tests grün (Stand 0.1.1) (`python3 -m pytest -q tests`, Python 3.12.3, SQLite 3.45.1, 08.11.2026).
- **Gespräch je Sitzung** (Zeitscheibe): `Mcp-Session-Id` → eigene Seriennummer, eigener Verlauf; Zustände
  `offen`/`beendet`/`abgelaufen`/`unterbrochen`. *Nachweis:* `test_zwei_sitzungen_zwei_gespraeche`,
  `test_sitzung_gespraech_und_sichern`.
- **Instanzen mit eigenem Token** (nur SHA-256 gespeichert), Urheber-Hashtag `instanz:<name>`, Reflex-Recht je
  Instanz. *Nachweis:* `test_schutz` (401/403/400/404/405), `test_fremde_sitzung_und_reflex_recht`.
- **Hook-Werkzeuge `vi_vorher`/`vi_nachher`**: jeder Client kann Handlungen melden — die VI ist nicht mehr in
  einen bestimmten Werkzeug-Server eingebaut. *Nachweis:* `test_gemerkte_antwort_nur_lesend`, `test_erkenntnis_als_hinweis_vorher`.
- **Claude-Code-Hook** `hook/vi_hook.py` ([docs/HOOK.md](docs/HOOK.md)): meldet jede Handlung jeder Sitzung
  (PreToolUse/PostToolUse/PostToolUseFailure/SessionEnd); gemerkte Antwort → Aufruf verweigert mit der Antwort als
  Grund; eingebaute Werkzeuge nie aus dem Gedächtnis; Ausfall läuft durch und wird protokolliert.
  *Nachweis:* `tests/test_hook.py`, 7 Tests gegen echten Server; Schnittstelle nach https://code.claude.com/docs/en/hooks.md.
- **Debian-Paket** `vi-mcp_0.1.0-1_all.deb` (`deploy/debian/build.sh`): Systemdienst mit eigenem Nutzer `vi-mcp`,
  `/etc/vi-mcp`, `/var/lib/vi-mcp`, gehärtete Unit. **Installiert auf <host>** (08.11.2026 11:50 UTC).
  *Nachweis (am echten Host, Python-Client auf 127.0.0.1:8765):* `initialize` 200 (Protokoll 2025-06-18),
  `vi_lerne` + `vi_status` ok, FTS5 aktiv, `DELETE` 204 → danach 404, ohne Token 401; `vi.db*` `vi-mcp:vi-mcp 0600`;
  `/etc/vi-mcp/config.json` nach `vi-mcp instanz` weiter `root:vi-mcp 0640`; `systemd-analyze security` 3.6 OK.
- **systemd-User-Dienst** `deploy/vi-mcp.service` + `deploy/install.sh`. *Nachweis:* noch keiner — siehe „Was fehlt noch“.

### Was hat sich geändert (gegenüber dem VI-Teil des stdio-Skill-Servers 3.0.0)

- Gesprächsnummer wird **numerisch** verglichen: das 1000. Gespräch eines Tages bekommt `…1000` statt eines
  Fehlers. *Nachweis:* `test_seriennummer_ueber_999`; Parallelität: `test_seriennummern_eindeutig_parallel` (20 Threads).
- Zugriffszähler wird **atomar** hochgezählt (`zugriffe = zugriffe + 1`), kein verlorener Zähler.
  *Nachweis:* `test_zugriff_zaehlt_relativ`.
- Datenbank, Konfiguration, Verzeichnisse nur für den Eigentümer (0600/0700); `busy_timeout` 30 s statt 5 s.
  *Nachweis:* `test_datei_nur_fuer_eigentuemer`.
- Client darf `lesend` ausdrücklich angeben; sonst gilt das Namensmuster.
- Reflex-Prüfung strenger (`getattr`, `setattr`, Dunder-Attribute, `remove`/`unlink` verboten); Modul `_common`
  entfällt (gehörte zum Skill-Server). Defekte Reflexe werden entladen und als `modus:defekt` getaggt.
  *Nachweis:* `test_reflex_pruefung`, `test_reflex_defekt_nach_drei_fehlern`.
- Loop-Fehler werden gezählt und in `vi_status` genannt statt nur ins Protokoll geschrieben.

### Was wurde behoben

- `bestaetige`/`widerlege` erhöhten den Zähler **vor** der Prüfung des Grundes; ein abgelehnter Aufruf zählte
  trotzdem, der nächste doppelt. Jetzt: erst prüfen, dann ändern.
  *Nachweis:* `test_objekt_grund_pflicht_und_geschichte` (schlug mit dem übernommenen Code fehl: `2 == 1`).
- Zwei gleiche Handlungen in derselben Sekunde ergaben dieselbe Objekt-ID; die zweite überschrieb die erste still.
  Jetzt mit Zufallsanteil in der ID. *Nachweis:* `test_eingebaute_werkzeuge_nie_aus_gedaechtnis` (schlug vorher fehl: `1 == 2`).
- Ein gemeldetes `vorher` ohne `nachher` verschwand spurlos. Jetzt: Erfahrung `ok:unbekannt` beim Sitzungsende
  bzw. nach 1 h. *Nachweis:* `test_vorher_ohne_nachher_verschwindet_nicht`, `test_zwei_sitzungen_zwei_gespraeche`.

### Was fehlt noch

- **Von außen nicht erreichbar**: auf <host> lauscht vi-mcp nur auf 127.0.0.1. Clients auf anderen Hosts
  brauchen eine TLS-Route (nginx dort) oder einen SSH-Tunnel — noch nicht entschieden.
- Warteschlange des Servers ist die Python-Vorgabe (Listen-Backlog 5, `ss -ltn` auf <host>) — bei vielen
  gleichzeitigen Clients erhöhen.
- Benutzerdienst-Variante (`deploy/install.sh`) lokal nicht ausgeführt (Persistenz braucht Freigabe).
- **Nicht bei Claude Code registriert**; solange der alte stdio-Skill-Server seine eingebaute VI weiterbetreibt,
  gäbe es zwei Gedächtnisse mit gleichnamigen Werkzeugen — erst dort entfernen, dann hier anschließen.
- **Altes Gedächtnis nicht übernommen** (`~/skills/vi.db`, Stand 08.11.: nur 4 Gesprächsobjekte, sonst leer).
- **Hook nicht eingetragen** (braucht Freigabe, siehe docs/HOOK.md); Laufzeit je Werkzeugaufruf noch nicht gemessen.
  `additionalContext` bei PreToolUse ist in der Doku nicht bestätigt.
- **Ein Host**: mehrere Hosts brauchen einen TLS-Proxy davor bzw. bei mehreren Schreibern PostgreSQL.
- **Reflexe ohne Prozess-Isolat** (laufen im Serverprozess, nur AST-Prüfung + Zeitlimit).
- Geplant: Reflexion per LLM im Loop (Erfahrungen → Erkenntnisse), gelernte Suchen aus wiederkehrenden Filtern,
  Vergessen/Archiv, weitere Reize (Wörter aus Filtern, Tageszeit).
