# Ask Ubuntu — Häufig gestellte Fragen

## Erste Schritte

### Wie starte ich Ask Ubuntu?

**CLI:** Führe `./ask-ubuntu` (oder `ask-ubuntu`, falls als snap installiert) in einem Terminal aus.

**GUI:** Starte die Anwendung über den App-Launcher oder führe `cd electron && npm start` in einem Terminal aus.

Für lokale Modelle starte zuerst Lemonade Server:
```bash
lemonade-server start
```

Wenn du einen entfernten Anbieter konfiguriert hast (Anthropic, OpenAI, Gemini oder benutzerdefiniert), verwendet Ask Ubuntu ihn automatisch, wenn Lemonade nicht verfügbar ist.

### Was ist Lemonade Server?

Lemonade Server ist die lokale KI-Inferenz-Engine, die Ask Ubuntu verwendet, um das Sprachmodell auf deinem eigenen Rechner auszuführen. Er läuft auf Port 8000. Installiere ihn vom Lemonade-Projekt auf GitHub.

Lemonade ist optional, wenn du einen entfernten Anbieter konfigurierst — Ask Ubuntu kann stattdessen eine Verbindung zu Cloud-APIs herstellen.

### Sendet Ask Ubuntu Daten ins Internet?

**Mit lokalen Modellen (Lemonade):** Nein. Die KI-Inferenz läuft auf deinem Rechner. Man-Pages können bei der ersten Verwendung von manpages.ubuntu.com abgerufen werden (um den lokalen Cache aufzubauen), dies ist jedoch nur lesend und ohne Authentifizierung.

**Mit entfernten Anbietern:** Ja. Deine Fragen und der Systemkontext werden an die API des Anbieters gesendet (Anthropic, OpenAI, Gemini oder deinen benutzerdefinierten Endpunkt). Falls Datenschutz ein Anliegen ist, verwende ein lokales Lemonade-Modell.

### Wie lange dauert der erste Start?

**Mit Lemonade:** Beim ersten Start wird das KI-Modell heruntergeladen (~2–5 GB) und ein Dokumentationsindex erstellt (~2–3 Minuten). Nachfolgende Starts laden alles aus dem Cache und dauern nur wenige Sekunden.

**Mit einem entfernten Anbieter:** Startet in wenigen Sekunden — kein Modell-Download oder Index-Aufbau erforderlich.

---

## Ask Ubuntu verwenden

### Wie stelle ich eine Frage?

Tippe einfach an der `●`-Eingabeaufforderung und drücke Enter. Es ist keine besondere Syntax erforderlich.

### Kann ich mehrzeiligen Text wie eine Fehlermeldung einfügen?

Ja. Drücke `Esc` und dann `Enter`, um in der CLI-Eingabeaufforderung einen Zeilenumbruch einzufügen. Drücke `Enter` allein zum Absenden. In der GUI verwendest du `Shift+Enter` für Zeilenumbrüche.

### Wie starte ich ein neues Gespräch?

**CLI:** Das Gespräch wird zurückgesetzt, wenn du `./ask-ubuntu` neu startest.

**GUI:** Klicke auf die Schaltfläche **+** (neuer Chat) oben in der linken Seitenleiste.

### Wie leere ich den CLI-Bildschirm?

Tippe `/clear` an der Eingabeaufforderung.

### Wie beende ich Ask Ubuntu?

**CLI:** Tippe `/exit`, `/quit` oder drücke `Ctrl+D`.

**GUI:** Schließe das Fenster.

### Kann Ask Ubuntu Befehle auf meinem Computer ausführen?

Nein. Ask Ubuntu liest den Systemzustand (Paketlisten, Dienststatus, Live-Statistiken), führt jedoch niemals Befehle aus oder nimmt Änderungen an deinem System vor. Es teilt dir mit, welchen Befehl du ausführen sollst; du führst ihn selbst aus.

---

## Modelle

### Wie wählt Ask Ubuntu das zu verwendende KI-Modell?

Es erkennt deine Hardware automatisch:
1. Wenn du eine AMD NPU (Ryzen AI, Strix Point) hast und das FLM-Backend installiert ist, wird das beste heruntergeladene FLM-Modell verwendet (Qwen3-8b-FLM, Phi-4-Mini-FLM oder Llama-3.2-3B-FLM).
2. Andernfalls wird ein GGUF-Modell basierend auf deiner Hardware-Klasse ausgewählt (leistungsstarkes AMD, Intel, ausgewogenes AMD oder ältere Hardware).
3. Wenn Lemonade nicht läuft und ein entfernter Anbieter konfiguriert ist, wechselt es automatisch zum entfernten Anbieter.

### Wie ändere ich das KI-Modell?

**CLI:** Tippe `/model`, um die interaktive Modellauswahl zu öffnen. Sie zeigt sowohl lokale (Lemonade) als auch entfernte (Cloud) Modelle. Benutze die Pfeiltasten zur Navigation, tippe zum Suchen, drücke Enter zur Auswahl.

**GUI:** Klicke auf die Schaltfläche **⊙** (Modell-Symbol) oben in der linken Seitenleiste. Wechsle zwischen den Tabs **Lokal** und **Remote**.

### Was bedeuten die Modell-Badges?

- **Recommended** — das Modell, das Ask Ubuntu für deine Hardware am besten geeignet hält
- **NPU** — entwickelt für den Betrieb auf der AMD NPU mit dem FLM-Backend
- **Downloaded** — bereits auf dem Datenträger; wird sofort geladen
- **☁** (Cloud-Symbol in der CLI) — ein entferntes Cloud-Modell
- Kein Badge — wird beim Auswählen heruntergeladen (kann einige Minuten dauern)

### Wie lade ich ein neues Modell herunter?

Wähle im Tab „Lokal" der Modellauswahl (CLI `/model` oder GUI ⊙-Schaltfläche) ein beliebiges Modell aus, das noch nicht heruntergeladen wurde. Ask Ubuntu lädt es automatisch herunter und wechselt zu ihm. Entfernte Modelle erfordern keinen Download.

### Kann ich ein bestimmtes Modell festlegen?

Ja. Starte Ask Ubuntu mit `--model <model-id>` auf der CLI oder setze die Umgebungsvariable `ASK_UBUNTU_MODEL` für die GUI. Für ein entferntes Modell verwende `--provider` und optional `--model`:

```bash
./ask-ubuntu --provider anthropic --model claude-sonnet-4-6
```

### Was ist das FLM-Backend?

FastFlowLM (FLM) ist ein Backend zur nativen Ausführung quantisierter Sprachmodelle auf der AMD NPU (Neural Processing Unit). Es ist deutlich schneller und energieeffizienter als der Betrieb auf der CPU. Das FLM-Backend wird separat als Teil des Lemonade NPU-Stacks installiert.

### Welche Modelle sind verfügbar?

Im Katalog von Lemonade befinden sich ~70 Chat-Modelle, darunter Llama, Qwen, Phi, Mistral und andere in verschiedenen Größen und Formaten (FLM für NPU, GGUF für CPU/GPU). Nutze die Modellauswahl, um alle zu durchsuchen.

---

## Entfernte Anbieter

### Welche entfernten Anbieter werden unterstützt?

Ask Ubuntu unterstützt jede OpenAI-kompatible API. Integrierte Voreinstellungen:

| Anbieter | Modelle |
|----------|---------|
| Anthropic | Claude Opus 4.6, Claude Sonnet 4.6, Claude Haiku 4.5 |
| OpenAI | GPT-4o, GPT-4o Mini, o3-mini |
| Google Gemini | Gemini 2.0 Flash, Gemini 2.5 Pro, Gemini 1.5 Pro |
| Benutzerdefiniert | Jeder OpenAI-kompatible Endpunkt (Ollama, LiteLLM, vLLM usw.) |

### Wie konfiguriere ich einen entfernten Anbieter?

**Am schnellsten — Umgebungsvariable:**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
./ask-ubuntu
```

**CLI — interaktiv:**
Tippe `/providers` und folge den Anweisungen, um einen Anbieter hinzuzufügen.

**CLI — einmalig:**
```bash
./ask-ubuntu --provider openai --api-key sk-...
```

**GUI:**
Öffne die Modellauswahl (⊙-Schaltfläche) → Tab „Remote" → Formular ausfüllen → Save.

### Wo wird die Konfiguration entfernter Anbieter gespeichert?

In `~/.config/ask-ubuntu/remote_providers.json` (oder `$SNAP_USER_DATA/config/remote_providers.json` in einem snap). Über Umgebungsvariablen gesetzte API-Schlüssel werden niemals auf die Festplatte geschrieben.

### Kann ich Ollama als benutzerdefinierten Anbieter hinzufügen?

Ja. Verwende die benutzerdefinierte Anbieter-Option und setze:
- **Basis-URL:** `http://<hostname>:11434/v1` (Ollamas OpenAI-kompatibler Endpunkt)
- **API-Schlüssel:** `ollama` (oder eine beliebige nicht-leere Zeichenkette — Ollama prüft sie nicht)
- **Name:** beliebig (z. B. „Mein Ollama")

Ask Ubuntu erkennt automatisch die von Ollama heruntergeladenen Modelle. Schlägt die Erkennung fehl (z. B. weil der Server nicht erreichbar ist), kannst du den Modellnamen manuell eingeben.

### Funktioniert die Dokumentensuche (RAG) mit entfernten Anbietern?

Nein. RAG erfordert ein lokales Einbettungsmodell, das über Lemonade geladen wird. Bei der Verwendung eines entfernten Anbieters antwortet Ask Ubuntu nur auf Basis seines Trainingswissens und deines Systemkontexts.

### Was passiert, wenn Lemonade während einer Sitzung abstürzt?

Nur neue Sitzungen wechseln automatisch. Wenn Lemonade stoppt, während du bereits chattest, verwende `/model`, um für die aktuelle Sitzung zu einem entfernten Modell zu wechseln, oder starte Ask Ubuntu neu.

---

## Systeminformationen

### Welche Systeminformationen sammelt Ask Ubuntu?

Beim Start: Betriebssystem-Details, CPU-Modell/Kerne/Governor, GPU-Name und Arbeitsspeicher, RAM-Auslastung, Datenträger-Einhängepunkte, Akku, Thermalbereiche, installierte snaps und deb-Pakete, laufende Dienste. In der GUI findest du eine Kurzübersicht in der linken Seitenleiste.

### Kann Ask Ubuntu meine Dateien einsehen?

Nein. Ask Ubuntu liest Systemmetadaten (Paketlisten, Dienststatus, Hardware-Informationen), liest jedoch niemals deine persönlichen Dateien, den Inhalt deines Home-Verzeichnisses oder Dateien, die du nicht explizit in den Chat eingefügt hast.

### Warum zeigt die Systeminformation in der Seitenleiste eine Warnmeldung zur Temperatur?

Eine Temperaturwarnung erscheint, wenn ein CPU- oder GPU-Thermalbereich beim Start 60 °C oder höher meldet. Dies ist rein informativ — Ask Ubuntu teilt dir mit, dass dein Rechner warm ist. Frage es „is my laptop overheating?" für eine detaillierte Analyse.

### Wie aktualisiere ich die Systeminformationen?

Die Systeminformationen werden beim Start gesammelt. Starte Ask Ubuntu neu (oder öffne eine neue Sitzung), um eine aktuelle Momentaufnahme zu erhalten. Live-Statistiken (RAM, CPU, GPU während des Gesprächs) werden bei Bedarf über das Tool `get_system_stats` abgerufen, wenn du Fragen zur aktuellen Ressourcennutzung stellst.

---

## Dokumentation und RAG

### Welche Dokumentation durchsucht Ask Ubuntu?

Es durchsucht einen lokalen Vektorindex von ~500 Ubuntu-Man-Pages und ~200 Ubuntu-Hilfeartikeln von help.ubuntu.com sowie das Ask Ubuntu-Benutzerhandbuch selbst. Dieser Index wird beim ersten Ausführen erstellt und unter `~/.cache/ask-ubuntu/` gespeichert.

### Warum kennt Ask Ubuntu eine bestimmte Man-Page nicht?

Der Index enthält die am häufigsten referenzierten Befehle. Wenn eine Man-Page fehlt, versucht Ask Ubuntu trotzdem, aus seinem Trainingswissen zu antworten. Du kannst es auch bitten, einen bestimmten Befehl zu prüfen: „show me the man page for rsync".

### Wie erzwinge ich einen Neuaufbau des Dokumentationsindex?

```bash
rm ~/.cache/ask-ubuntu/faiss_index_* ~/.cache/ask-ubuntu/documents_*.pkl
```

Starte dann Ask Ubuntu neu. Der Index wird von Grund auf neu erstellt (2–3 Minuten).

### Wie erhalte ich lokale Man-Pages statt abgerufener?

Verbinde die snap-Schnittstelle `system-packages-doc` (verfügbar auf Ubuntu 24.04+):
```bash
sudo snap connect ask-ubuntu:system-packages-doc
```

Dies gibt dem snap Lesezugriff auf `/usr/share/man/` für schnelle lokale Suche.

---

## Fehlerbehebung

### Ask Ubuntu meldet „Lemonade Server is not running"

Starte Lemonade Server:
```bash
lemonade-server start
```

Starte dann Ask Ubuntu neu.

### Die GUI bleibt bei „Starting backend…" hängen

1. Stelle sicher, dass Lemonade Server läuft: `curl http://localhost:8000/api/v1/health`
2. Überprüfe das Terminal auf `[server]`-Fehlerzeilen — ein Python-Importfehler oder ein Port-Konflikt wird dort angezeigt.

### Ein Modell-Download ist fehlgeschlagen oder hängt

Öffne die Modellauswahl erneut und versuche, dasselbe Modell erneut auszuwählen. Wenn es wiederholt fehlschlägt, prüfe, ob Lemonade Server Internetzugang hat und genügend Speicherplatz frei ist (~5 GB).

### Die Pfeiltasten der CLI-Modellauswahl funktionieren in meinem Terminal nicht

Manche Terminals (insbesondere sehr alte xterm-Varianten) leiten Escape-Sequenzen nicht korrekt weiter. Versuche ein anderes Terminal (GNOME Terminal, Alacritty, Kitty oder das integrierte Ubuntu-Terminal). Die Auswahl erfordert ein modernes Terminal mit ANSI-Escape-Code-Unterstützung.

### Mein snap kann /var/lib/apt/lists oder /var/lib/dpkg nicht lesen

Die snap-Schnittstellen müssen verbunden sein:
```bash
sudo snap connect ask-ubuntu:var-lib-apt-lists
sudo snap connect ask-ubuntu:var-lib-dpkg
```

Starte Ask Ubuntu nach der Verbindung neu.

### Ask Ubuntu gibt falsche Antworten über mein System

Bitte es, erneut mit einem Live-Tool zu prüfen: „run get_system_stats and tell me what it shows". Versuche auch, ein neues Gespräch zu beginnen — Systeminformationen werden zu Beginn jeder Sitzung gesammelt.

### Wie melde ich einen Fehler?

Öffne ein Issue im Ask Ubuntu-GitHub-Repository mit:
- Deiner Ubuntu-Version (`lsb_release -d`)
- Der Ask Ubuntu-Version oder dem git-Commit
- Der genauen Frage, die du gestellt hast, und der erhaltenen Antwort
- Jeglicher Fehlerausgabe aus dem Terminal

---

## Datenschutz und Sicherheit

### Sind meine Daten privat?

**Mit lokalen Modellen (Lemonade):** Ja. Alle Inferenz läuft lokal auf deinem Rechner. Nichts wird an einen entfernten Server gesendet, außer:
- Man-Pages, die bei der ersten Verwendung von manpages.ubuntu.com abgerufen werden (ohne Authentifizierung, nur lesend)
- Hilfeseiten, die bei der ersten Verwendung von help.ubuntu.com abgerufen werden (ohne Authentifizierung, nur lesend)

**Mit entfernten Anbietern:** Deine Fragen und der Systemkontext werden an die API des Anbieters gesendet. Lies die Datenschutzrichtlinie des von dir gewählten Anbieters (Anthropic, OpenAI, Google oder deinen benutzerdefinierten Endpunkt). Über die Benutzeroberfläche gespeicherte API-Schlüssel werden lokal in `~/.config/ask-ubuntu/remote_providers.json` abgelegt.

### Kann Ask Ubuntu mein System verändern?

Nein. Es liest den Systemzustand, führt jedoch niemals Befehle aus und schreibt nicht in deine Dateien. Es teilt dir mit, was du ausführen sollst; du entscheidest, ob du es tust.
