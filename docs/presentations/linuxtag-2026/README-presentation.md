# LinuxTag 2026 — openDesk an der Uni Marburg

Präsentation über die openDesk-Erfahrung an der Philipps-Universität Marburg.

**Datum:** 28.03.2026  
**Konferenz:** LinuxTag 2026

## Voraussetzungen

- Marp CLI: `npm install -g @marp-team/marp-cli`

## Erstellen

### HTML (empfohlen für interaktive Präsentation)
```bash
marp --no-config-file --allow-local-files linuxtag-2026-opendesk.md -o presentation.html
```

### PDF
```bash
marp --pdf --allow-local-files linuxtag-2026-opendesk.md -o presentation.pdf
```

### Backup-Folien
```bash
marp --pdf --allow-local-files linuxtag-2026-opendesk-backup.md -o backup.pdf
```

## Dateistruktur

```
linuxtag-2026-opendesk.md      # Hauptpräsentation (26 Folien)
linuxtag-2026-opendesk-backup.md  # Backup-Folien (12 Folien)
.marprc.yml                   # Marp-Konfiguration
media/                        # Bilder (4 Dateien)
```

## Lizenz

Interne Verwendung - HRZ Uni Marburg
