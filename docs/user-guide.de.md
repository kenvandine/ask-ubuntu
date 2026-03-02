# Ask Ubuntu — Benutzerhandbuch

Ask Ubuntu ist ein KI-Assistent für Ubuntu Linux. Er beantwortet Fragen zu deinem System, installierten Paketen, laufenden Diensten, Hardware, Konfiguration und allgemeiner Ubuntu-Nutzung. Er läuft vollständig lokal — keine Cloud, kein Internet für den Chat erforderlich.

---

## Was Ask Ubuntu beantworten kann

- „Wie installiere ich VLC?" — nennt dir den snap- oder apt-Befehl mit Versionsinformationen
- „Welche Version von Firefox habe ich?" — prüft deine tatsächlich installierte snap-Version
- „Warum läuft mein Laptop-Lüfter so laut?" — liest deine Thermosensoren und den CPU-Governor aus
- „Wie viel Speicherplatz ist frei?" — liest Live-Mount-Statistiken
- „Läuft nginx?" — prüft den systemd-Dienststatus in Echtzeit
- „Welche snap interfaces benötigt die Kamera-App?" — schlägt es im snap store nach
- „Wie aktiviere ich eine Firewall?" — liest die UFW-Manpage und gibt dir die genauen Befehle
- „Welche Prozesse verwenden meinen Arbeitsspeicher?" — ruft einen Live-Prozess-Snapshot ab und erklärt ihn

Ask Ubuntu kennt dein spezifisches Gerät vollständig. Wenn du fragst „Wie viel RAM habe ich?", antwortet es mit deinem tatsächlichen Arbeitsspeicher, nicht mit einer allgemeinen Erklärung.

---

## Ask Ubuntu starten

### Terminal CLI

```bash
./ask-ubuntu
```

Oder wenn als snap installiert:
```bash
ask-ubuntu
```

Ask Ubuntu startet, zeigt einen System-Info-Header und bringt dich zur Chat-Eingabeaufforderung.

### Desktop GUI

Starte aus dem App-Launcher oder aus dem Terminal:
```bash
cd electron && npm start
```

Die App öffnet ein geteiltes Fenster: Systeminfo-Panel links, Chat rechts.

### Ersteinrichtung

Beim allerersten Start wird Ask Ubuntu:
1. Das KI-Modell von Lemonade Server laden (~2–5 GB je nach Modell)
2. Das Einbettungsmodell für die Dokumentensuche laden (~500 MB)
3. Den Dokumentationsindex aufbauen — liest Manpages und Ubuntu-Hilfedateien (~2–3 Minuten)

Alles wird in `~/.cache/ask-ubuntu/` zwischengespeichert. Folgestarts laden sofort.

---

## Die CLI verwenden

### Fragen stellen

Gib eine beliebige Frage an der `●`-Eingabeaufforderung ein und drücke Enter:

```
● How do I check if a service is enabled?
```

Für **mehrzeilige Fragen** (z. B. beim Einfügen einer Fehlermeldung) drücke `Esc` dann `Enter`, um einen Zeilenumbruch einzufügen. Drücke `Enter` allein zum Absenden.

Verwende `↑` und `↓`, um durch den Fragenverlauf zu navigieren.

### Sonderbefehle

| Befehl | Funktion |
|--------|----------|
| `/model` | Interaktive Modellauswahl öffnen — KI-Modell wechseln |
| `/help` | Hilfetabelle anzeigen |
| `/clear` | Bildschirm leeren |
| `/exit` oder `/quit` | Ask Ubuntu beenden |
| `Ctrl+D` | Beenden |

### Modell in der CLI wechseln

Gib `/model` ein, um eine bildschirmfüllende interaktive Auswahl zu öffnen:

- **Tippen zum Suchen** — filtert die Modellliste sofort während der Eingabe
- `↑` / `↓` — durch die Liste navigieren
- `PgUp` / `PgDn` — schneller scrollen
- `Enter` — markiertes Modell auswählen
- `Esc` — abbrechen und aktuelles Modell behalten

Modelle werden sortiert, mit der besten Wahl für deine Hardware oben. Badges zeigen:

- **★ Recommended** — beste Übereinstimmung für deine Hardware
- **NPU** — für den AMD NPU ausgelegt (schnellste auf unterstützter Hardware)
- **✓ Downloaded** — bereits auf der Festplatte, lädt sofort
- *(kein Badge)* — wird beim Auswählen automatisch heruntergeladen (~2–5 GB)

Wenn du ein Modell auswählst, das noch nicht heruntergeladen wurde, lädt Ask Ubuntu es herunter und zeigt den Fortschritt vor dem Wechsel an.

### Antworten lesen

Antworten erscheinen als Streaming-Text. Code-Blöcke sind hervorgehoben. Wenn der Assistent vor der Antwort Live-Systemdaten abgerufen hat (z. B. Speichernutzung, Paketversionen), werden diese Tool-Aufrufe in zusammengeklappten Detail-Zeilen vor der Antwort angezeigt:

```
  ↳ check_snap(firefox)
  ↳ get_system_stats()
```

---

## Die Desktop GUI verwenden

### Fensterlayout

Das Fenster hat zwei Panels:

**Linke Seitenleiste** — dein Systeminfo-Snapshot:
- Betriebssystem, Kernel, Hostname, Formfaktor (Laptop/Desktop)
- CPU, GPU, Arbeitsspeicher, Festplatte je Mount, Akku
- Aktive Thermowarnungen
- Installierte Paketanzahl (snap und deb)
- Oben: **Modellauswahl-Button** und **Neuer-Chat-Button**

**Rechtes Panel** — der Chat-Bereich:
- Deine Nachrichten erscheinen rechts in Orange
- Assistenten-Antworten erscheinen links
- Ein pulsierender Punkt zeigt an, wenn das Modell denkt
- Tool-Aufrufe (Paketnachschläge, Live-Statistiken) erscheinen als aufklappbare Details

### Modell in der GUI wechseln

Klicke auf das **⊙**-Symbol (Modell/Sunburst) oben in der linken Seitenleiste. Dies öffnet das Modellauswahl-Overlay:

- **Suchfeld** — tippe, um die Modellliste sofort zu filtern
- Jede Zeile zeigt Modellname, Größe und Status-Badges
- Klicke auf eine Zeile, um sie auszuwählen
- Wenn das Modell noch nicht heruntergeladen wurde, erscheint ein Fortschrittsbalken — warte auf den Abschluss des Downloads, bevor du chattest

Badges:
- **Recommended** (orange) — beste Wahl für deine Hardware
- **NPU** (blau) — läuft auf dem AMD NPU
- **Downloaded** (grün) — bereits verfügbar

### Neues Gespräch starten

Klicke auf den **+**-Button (Neuer Chat) in der Seitenleiste, um das Gespräch zu löschen und neu zu beginnen. Frühere Nachrichten werden nicht gespeichert.

### Code-Blöcke

Jeder Code-Block in einer Antwort hat einen **Copy**-Button. Klicke darauf, um den Befehl in die Zwischenablage zu kopieren. Der Button blinkt zur Bestätigung des Kopiervorgangs.

---

## Wie Ask Ubuntu das KI-Modell auswählt

Beim Start wählt Ask Ubuntu automatisch das beste verfügbare Modell für deine Hardware:

### 1. NPU + FLM (höchste Priorität)

Wenn du einen AMD NPU (XDNA oder XDNA2 — vorhanden in Ryzen AI- und Strix-Point-Prozessoren) hast und das FastFlowLM (FLM)-Backend installiert ist, verwendet Ask Ubuntu ein dediziertes FLM-Modell, das nativ auf dem NPU läuft. Dies ist die schnellste und energieeffizienteste Option.

FLM-Modell-Präferenzreihenfolge:
1. Qwen3-8b-FLM (8 Milliarden Parameter, beste Qualität)
2. Phi-4-Mini-Instruct-FLM (4B, schneller)
3. Llama-3.2-3B-FLM (3B, kleinste)

Nur bereits heruntergeladene FLM-Modelle werden automatisch ausgewählt. Wenn keine vorhanden sind, fällt es auf die Hardware-Stufe zurück.

### 2. Hardware-Stufe (Fallback)

| Stufe | Hardware | Modell |
|-------|----------|--------|
| High-End | AMD Strix / Ryzen AI (GPU) | Qwen3-4B-Instruct-2507-GGUF |
| Mid-Intel | Intel Core / Ultra | Phi-4-mini-instruct-GGUF |
| Balanced AMD | AMD CPU, ≥ 16 GB RAM | Llama-3.2-3B-Instruct-GGUF |
| Legacy | Sonstige / wenig RAM | Llama-3.2-1B-Instruct-GGUF |

### Ein bestimmtes Modell festlegen

```bash
# CLI — auf der Kommandozeile übergeben
./ask-ubuntu --model Llama-3.2-3B-Instruct-GGUF

# GUI — Umgebungsvariable vor dem Start setzen
ASK_UBUNTU_MODEL=Llama-3.2-1B-Instruct-GGUF npm start
```

---

## Wie der Systemkontext funktioniert

Vor deiner ersten Nachricht erfasst Ask Ubuntu einen Snapshot deines Rechners:

- Vollständige Betriebssystemidentifikation (Ubuntu-Version, Codename, Kernel)
- CPU-Modell, Kernanzahl, Hyperthreading, L3-Cache, aktiver CPU-Frequenz-Governor
- GPU-Name, VRAM- und GTT-Speichernutzung, Temperatur, Taktfrequenz (AMD)
- RAM: genutzt, verfügbar, gecacht; Swap-Nutzung; Speicherdruck (PSI)
- Festplatte: Laufwerkstyp (NVMe SSD / HDD), LVM/LUKS/RAID-Erkennung, Nutzung je Mount
- Netzwerkschnittstellen: Typ, Zustand, Geschwindigkeit
- Akkuladung und -status (Laptops)
- Thermische Zonen — warnt dich, wenn eine Zone heiß ist
- Alle installierten snaps und deb-Pakete
- Laufende systemd-Dienste

Dieser Kontext wird bei jeder Frage mitgesendet, sodass Antworten immer spezifisch für deinen Rechner sind.

Das LLM kann auch **Live-Tools** während des Gesprächs aufrufen, um aktuelle Daten zu erhalten:

| Tool | Was es abruft |
|------|--------------|
| `check_snap(name)` | Installierte Version + Store-Version eines snap |
| `check_apt(name)` | Ob ein deb-Paket installiert oder verfügbar ist |
| `list_installed_snaps()` | Alle installierten snaps mit Versionen |
| `check_service(name)` | Ob ein systemd-Dienst aktiv und aktiviert ist |
| `list_running_services()` | Alle laufenden Daemons |
| `list_failed_services()` | Alle fehlgeschlagenen systemd-Units |
| `get_system_stats()` | Live-Speicher-, GPU-, CPU-Nutzung, Top-Prozesse, Festplatte |

---

## Wie die Dokumentenabfrage (RAG) funktioniert

Ask Ubuntu verfügt über einen lokalen Vektorindex der Ubuntu-Dokumentation. Vor der Beantwortung deiner Frage durchsucht es diesen Index nach den 3 relevantesten Dokumenten und fügt sie als Kontext für das KI-Modell ein.

Der Index enthält:
- ~500 Ubuntu-Manpages (apt, snap, systemctl, ufw usw.)
- ~200 Ubuntu-Hilfeartikel von help.ubuntu.com
- Das Ask Ubuntu-Benutzerhandbuch und FAQ (dieses Dokument)

Manpages werden geladen von:
1. `/usr/share/man/` wenn das snap interface `system-packages-doc` verbunden ist
2. Dem lokalen Festplatten-Cache in `~/.cache/ask-ubuntu/manpages/`
3. Von manpages.ubuntu.com bei der ersten Verwendung (dann gecacht)

Der Index wird in `~/.cache/ask-ubuntu/` gespeichert. Lösche ihn, um einen Neuaufbau zu erzwingen:
```bash
rm ~/.cache/ask-ubuntu/faiss_index_* ~/.cache/ask-ubuntu/documents_*.pkl
```

---

## Tipps für gute Fragen

- **Sei spezifisch** — „warum ist apt langsam?" liefert eine bessere Antwort als „repariere meine Pakete"
- **Füge den Fehler ein** — füge die genaue Fehlermeldung ein, Ask Ubuntu wird sie erklären
- **Stelle Folgefragen** — Ask Ubuntu erinnert sich an den Gesprächskontext
- **Frage nach Befehlen** — „gib mir den Befehl, um meine GPU-Temperatur zu prüfen" gibt einen sofort ausführbaren Befehl zurück
- **Frage nach deinem System** — „läuft Wayland oder X11?", „auf welchen CPU-Governor ist mein System eingestellt?"

---

## Unterstützte Ubuntu-Versionen

Ask Ubuntu läuft auf Ubuntu 22.04 LTS (Jammy) und 24.04 LTS (Noble). Es erfordert Python 3.10+ und Lemonade Server, der lokal auf Port 8000 läuft.
