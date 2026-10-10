# Status Paket C (Rechnerverwaltung + Erkennung) – Stand 2026-10-10

## Erledigt
- Mockup fertig: `docs/mockups/paket-c.html` (Doppelklick genügt; 7 Szenen je Desktop und 375 px). Auf PBs Einstellungsseite abgestimmt (Speichern pro Abschnitt, Kennung `nodes`).
- Backend fertig und mit drei lokalen Instanzen getestet (`scripts/test-nodes.py`, alle Prüfungen grün): `nodes_store.py` (Liste, Token, Namen), `nodes.py` (Einstellungen, REST, Snapshot, Migration), `nodes_pair.py` (Kopplung), `nodes_scan.py` (Suche), `cluster.py` (ein Abfrage-Task je Rechner, Proxy/Übergabe mit Token), Token-Prüfung und öffentliche Pfade in `auth.py`.
- Zusätzlich von Hand geprüft: Rechner mit `AUTH_PASS` (ohne Kopplung 401/offline, nach Kopplung läuft Status und Proxy mit Token), Rechner offline und zurück, alter Stand ae4603e als dritte Instanz.

- Oberfläche gebaut (Mockup freigegeben): `js/nodes.js` (Abschnitt `nodes`: Name, Betriebsart, Auffindbarkeit, Rechnerliste, Suche, Hinzufügen per Adresse, Umbenennen/Testen/Koppeln/Entkoppeln/Entfernen), `js/nodes-pair.js` (Hinweisleiste + Bestätigungsdialog auf jeder Seite, Meldungen zu eigenen Anfragen, Hinweis bei neu gefundenen Rechnern), `js/nodes-util.js` (Hilfen, auch für PF: `peerUsable(p)`, `peerCan(p, name)`, `encoderChips(p)`), `css/nodes.css`; Text in `handover.js` bei leerer Liste.
- Geprüft im Browser mit PBs Einstellungsseite (temporär zusammengeführt, danach verworfen) und im alten Dialog: Liste, Suche, Koppeln samt Dialog auf der Gegenseite (zwei Tabs), Verbindungstest, Umbenennen, Eigenständig (ungespeichert-Anzeige, Speichern, Liste ruht, `peers` leer), Konsole ohne Fehler, bei 375 px kein waagerechter Überlauf (per DOM geprüft).
- Fehler beim Test gefunden und behoben: Die Suche las die HTTP-Antwort nur bis zum ersten Stück (Kopf und Inhalt kommen oft getrennt) und fand dadurch Rechner nicht zuverlässig.
- Nicht per Screenshot geprüft: 375-px-Darstellung der Oberfläche (die Browser-Pane war zu dem Zeitpunkt nicht sichtbar); Aufbau ist das freigegebene Mockup, die CSS stammt daraus.

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

### `/api/state` → `node` (dieser Rechner, leicht; andere Rechner lesen es mit) und `nodemgr` (für die eigene Oberfläche)
```json
"node": {"id": "5f0c…", "name": "vierstein", "mode": "verbund", "discoverable": true, "version": "0.4.0",
         "started": 1759900000.0, "cores": 4, "mem": 7516192768},
"nodemgr": {"nodes": [{"nid": "…", "name": "maintux", "url": "http://…:8780", "id": "…", "trust": "paired|legacy", "origin": "peers|manual|pairing", "added": 1.0, "paired": true}],
            "pairing": {"incoming": [{"rid": "…", "name": "vierstein", "url": "…", "version": "0.4.0", "code": "482913", "age": 20}],
                        "outgoing": [{"rid": "…", "url": "…", "name": "maintux", "code": "482913", "status": "waiting|ok|denied|expired|cancelled", "error": "", "age": 3}]},
            "scan": {"running": true, "done": 187, "total": 254, "nets": ["192.168.178.0/24"], "found": [{"id": "…", "name": "maintux", "url": "…", "version": "0.4.0", "cores": 32, "mem": 1, "self": false, "known": "", "paired": false}], "error": ""},
            "env_peers": false}
```
(`nodemgr.nodes` bleibt auch im eigenständigen Betrieb gefüllt, `peers` ist dort leer.)

### Backend für andere Pakete
- `from app import cluster`: `cluster.peer_call(name, "library/convert", {...}, timeout=15.0)` ruft einen Rechner der Liste mit Token auf (wirft bei Fehler); Proxy `POST /api/peer/{name}/{pfad}` unverändert (Positivliste über `ext.allow_proxy`).
- Einstellungen `nodes`: `mode` (`standalone`|`verbund`), `discoverable`, `name`, `public_url`, `scan_nets`, `auto_search`.
- Endpunkte (öffentlich = ohne Passwort erreichbar, nötig vor der Kopplung):
  `GET /api/nodes` · `POST /api/nodes/check {url}` (erreichbar? `legacy`? `known`?) · `POST /api/nodes {url,name?}` (ohne Kopplung, nur alte Rechner) ·
  `PATCH /api/nodes/{nid} {name}` · `DELETE /api/nodes/{nid}` · `POST /api/nodes/{nid}/unpair` · `POST /api/nodes/{nid}/test`;
  Kopplung: `POST /api/nodes/pair {url}` -> `{rid, code, name}` · `POST /api/nodes/pair-outgoing/{rid}/cancel` · `POST /api/nodes/pair-incoming/{rid}/accept|deny`;
  zwischen Rechnern: `POST /api/nodes/pair-request` (öffentlich) · `GET /api/nodes/pair-poll/{rid}` (öffentlich, Geheimnis im Kopf) · `POST /api/nodes/pair-cancel/{rid}` (öffentlich) · `POST /api/nodes/unpair` (Token) · `GET /api/nodes/whoami` (öffentlich; nennt Name/ID nur mit gültigem Token);
  Suche: `GET /api/discovery/hello` (öffentlich, 404 wenn nicht auffindbar) · `POST /api/discovery/scan` · `GET /api/discovery/scan` · `POST /api/discovery/scan/cancel`.
- Für Entwicklung: `NODES_SCAN_TARGETS="127.0.0.1:8820-8822"` (Host/Port-Liste, ersetzt die Netzwahl), `NODES_SCAN_PORTS`.
- Tokens liegen nur in `DATA/nodes.json` (Rechte 600), nicht im Namensraum `nodes` (daher keine `secret`-Felder nötig).

## Brauche von anderen
- PB: Abgestimmt (Koordinator): Abschnitt `registerSettingsSection({id:'nodes', label:'Rechner', order:30, icon, description, …})`; PB speichert pro Abschnitt `collect()` = `{nodes:{name, mode, discoverable, scan_nets, auto_search}}`. Die Rechnerliste (Koppeln, Suchen, Hinzufügen, Umbenennen, Entfernen) ist kein Formularfeld, sondern ruft eigene Endpunkte direkt auf; bei Änderungen an Bedienelementen löse ich `change` aus. Das Mockup hat deshalb keinen eigenen Speichern-Knopf. Status: erledigt.
- PZ (optional): In `main.py` kann die Bedingung `if cluster.parse_peers(PEERS_RAW): create_task(cluster.peer_prober())` entfallen; der Prober startet jetzt über `nodes.py` und läuft nur einmal (Doppelstart ist abgesichert).
- PZ: Docker/Compose brauchen nichts. Wer die Erkennung im Docker-Bridge-Netz nutzt, trägt bei Bedarf `nodes.scan_nets` ein.

## Fremde Dateien angefasst
(keine)

## Fragen an den Nutzer
1. Soll ein gekoppelter Rechner auch ohne `AUTH_PASS` Token verlangen (nur gekoppelte Rechner dürfen Aufträge übergeben/Laufwerke steuern)? Vorschlag: nein, im offenen LAN bleibt es wie bisher; das Token wirkt dort, wo `AUTH_PASS` gesetzt ist, und identifiziert die Gegenseite.
2. Der eigene Name (`nodes.name`) wird angezeigt und an andere Rechner weitergegeben; Sperrdateien und `capacity.instance` behalten den Hostnamen (INSTANCE_NAME), weil `config.INSTANCE` beim Import in viele Module gebunden ist. Reicht das, oder soll der Name überall gelten (dann Änderung in P0-Modulen nötig)?
3. Eine Kopplungsanfrage läuft 10 Minuten. Reicht das?

## Bekannte Grenzen
- Das Token geht beim Koppeln unverschlüsselt (HTTP) durchs LAN; geschützt wird vor fremden Aufrufen bei gesetztem `AUTH_PASS`, nicht vor Mitlesen im Netz. Ohne `AUTH_PASS` bleibt das LAN wie bisher offen.
- Wechselt ein Rechner die IP (DHCP), meldet der Eintrag `id_mismatch: true` bzw. offline; die Adresse lässt sich noch nicht ändern (Entfernen und neu koppeln). Kann nach Mockup-Freigabe als „Adresse ändern“ ergänzt werden.
- Ein Rechner, der bei der Suche nicht antwortet (alter Stand oder nicht auffindbar), ist nur per Adresse hinzufügbar.
