# Status Paket C (Rechnerverwaltung + Erkennung) – Stand 2026-10-10

## Erledigt
- Mockup fertig: `docs/mockups/paket-c.html` (Doppelklick genügt; Desktop und 375 px je Szene, 7 Szenen).

## In Arbeit
- Backend: `app/nodes_store.py`, `nodes.py`, `nodes_pair.py`, `nodes_scan.py`, Umbau `cluster.py`, Token-Prüfung in `auth.py`.
- Oberfläche (`js/nodes.js`, `css/nodes.css`) erst nach Freigabe des Mockups.

## Entscheidungen
- **Erkennung:** aktiver Scan des /24-Netzes (TCP-Verbindung + `GET /api/discovery/hello`), kein mDNS. Begründung: funktioniert im Docker-Bridge-Netz ohne `network_mode: host` und ohne neue Abhängigkeit; mDNS käme im Bridge-Netz nicht in den Container (und `network_mode: host` ändert Ports/Firewall: Sache von PZ). Welches Netz gescannt wird: (1) die Adresse, unter der der Browser die Seite aufgerufen hat (im Docker ist das die LAN-Adresse des Hosts, nicht die Container-IP), (2) die Netze bereits bekannter Rechner, (3) Einstellung `nodes.scan_nets` (CIDR-Liste), (4) nur ohne diese: Netze der eigenen Schnittstellen. Für die Entwicklung: Umgebungsvariable `NODES_SCAN_TARGETS` (z. B. `127.0.0.1:8820-8822`), ändert nichts am Produktionsverhalten.
- **Rechnerliste:** `DATA/nodes.json` (Rechte 600; enthält die Tokens, die deshalb nie in Einstellungen/`/api/state` landen). `PEERS` wird beim ersten Start übernommen (als „nicht gekoppelt, wie bisher vertraut“); später neu in `PEERS` stehende Adressen werden einmalig ergänzt, aber nie gelöschte wieder angelegt.
- **Kopplung:** Anfrage → Bestätigung auf dem anderen Rechner (mit 6-stelligem Code auf beiden Seiten) → gemeinsames Token. Aufrufe zwischen gekoppelten Rechnern tragen `X-Node-Token`; `auth.py` lässt sie auch bei gesetztem `AUTH_PASS` durch.

## Angebotene Schnittstellen
(Vorläufig, ändert sich nur mit Ankündigung hier.)

### `/api/state` → `peers[i]` (bestehende Felder bleiben, neu dazu)
```json
{
  "name": "maintux", "url": "http://192.168.178.189:8780", "reachable": true,
  "instance": "maintux", "cores": 32, "load": 4.1, "conv_active": 2, "conv_paused": false, "has_handover": true,
  "conversions": [], "uploads": [], "jobs": [], "drives": [], "output": {}, "now": 1760000000.0,
  "capabilities": {"version": "0.4.0", "features": ["handover"], "nodes": 1, "encoders": ["libx265", "libx264"]},

  "id": "5f0c…",              // Instanz-ID (leer bei alten Rechnern)
  "trust": "paired",          // "paired" (Token) | "legacy" (ohne Token, wie bisher) | "lost" (Gegenseite hat entkoppelt)
  "legacy": false,            // true = alter Stand ohne Kopplung/Fähigkeitsmeldung -> auf Fähigkeiten nicht verlassen
  "version": "0.4.0",         // "" bei alten Rechnern
  "mem": 33285996544, "started": 1759900000.0,
  "last_seen": 1760000000.0, "online_since": 1759990000.0
}
```
Ausführen-auf-Auswahl (PF): `p.reachable && !p.legacy` für neue Funktionen; für Funktionen eines v1-kompatiblen Auftrags reicht `p.reachable && p.has_handover`. Einzelne Fähigkeiten: `p.capabilities.encoders` usw. (nur, wenn `!p.legacy`). Im eigenständigen Betrieb ist `peers` leer (Verbund-Elemente verschwinden dadurch von selbst).

### `/api/state` → `node` (dieser Rechner)
```json
{"id": "5f0c…", "name": "vierstein", "mode": "verbund", "discoverable": true, "version": "0.4.0",
 "started": 1759900000.0, "cores": 4, "mem": 7516192768, "pairing": {"incoming": [], "outgoing": []},
 "scan": {"running": false, "found": []}}
```
### Backend für andere Pakete
- `from app import cluster`: `cluster.peer_call(name, "library/convert", {...}, timeout=15.0)` ruft einen Rechner der Liste mit Token auf (wirft bei Fehler); Proxy `POST /api/peer/{name}/{pfad}` unverändert (Positivliste über `ext.allow_proxy`).
- Einstellungen `nodes`: `mode` (`standalone`|`verbund`), `discoverable`, `name`, `public_url`, `scan_nets`, `auto_search`.
- Endpunkte: `GET /api/nodes`, `POST /api/nodes`, `PATCH|DELETE /api/nodes/{id}`, `POST /api/nodes/{id}/test`, `POST /api/nodes/pair`, `GET /api/discovery/hello`, `POST /api/discovery/scan`. (Genaueres folgt hier, sobald gebaut.)

## Brauche von anderen
- PB: Der Abschnitt „Rechner“ meldet sich per `registerSettingsSection({id:'nodes', label:'Rechner', order:30, …})` an (erst nach Freigabe des Mockups). Er speichert sich selbst (Namensraum `nodes`, auch eigene Aktionen wie „Koppeln“ sind direkte API-Aufrufe), `collect()` liefert nur `nodes`-Felder. Falls PBs Seite pro Abschnitt einen eigenen Speichern-Knopf vorsieht, bitte `collect()`-Ergebnis genauso behandeln. Status: offen (Hinweis).
- PZ (optional): In `main.py` kann die Bedingung `if cluster.parse_peers(PEERS_RAW): create_task(cluster.peer_prober())` entfallen; der Prober startet jetzt über `nodes.py` und läuft nur einmal (Doppelstart ist abgesichert).
- PZ: Docker/Compose brauchen nichts. Wer die Erkennung im Docker-Bridge-Netz nutzt, trägt bei Bedarf `nodes.scan_nets` ein.

## Fremde Dateien angefasst
(keine)

## Fragen an den Nutzer
1. Soll ein gekoppelter Rechner auch ohne `AUTH_PASS` Token verlangen (nur gekoppelte Rechner dürfen Aufträge übergeben/Laufwerke steuern)? Vorschlag: nein, im offenen LAN bleibt es wie bisher; das Token wirkt dort, wo `AUTH_PASS` gesetzt ist, und identifiziert die Gegenseite.
2. Soll der Name dieses Rechners in der Oberfläche nur angezeigt/weitergegeben werden (Vorschlag, Sperrdateien behalten den Hostnamen), oder überall ersetzt werden?
