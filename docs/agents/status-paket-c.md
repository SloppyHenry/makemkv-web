# Status package C (machine management + discovery) – as of 2026-10-10

## Done
- Mockup done: `docs/mockups/paket-c.html` (double-click is enough; 7 scenes each for desktop and 375 px). Aligned with PB's settings page (save per section, ID `nodes`).
- Backend done and tested with three local instances (`scripts/test-nodes.py`, all checks green): `nodes_store.py` (list, token, names), `nodes.py` (settings, REST, snapshot, migration), `nodes_pair.py` (pairing), `nodes_scan.py` (search), `cluster.py` (one query task per machine, proxy/hand-over with token), token check and public paths in `auth.py`.
- Additionally checked by hand: machine with `AUTH_PASS` (without pairing 401/offline, after pairing status and proxy work with the token), machine offline and back, old version ae4603e as a third instance.

- Interface built (mockup approved): `js/nodes.js` (section `nodes`: name, mode, discoverability, machine list, search, add by address, rename/test/pair/unpair/remove), `js/nodes-pair.js` (notice bar + confirmation dialog on every page, messages about own requests, notice for newly found machines), `js/nodes-util.js` (helpers, also for PF: `peerUsable(p)`, `peerCan(p, name)`, `encoderChips(p)`), `css/nodes.css`; text in `handover.js` for an empty list.
- Checked in the browser with PB's settings page (merged temporarily, then discarded) and in the old dialog: list, search, pairing including the dialog on the other side (two tabs), connection test, rename, standalone (unsaved indicator, save, list rests, `peers` empty), console free of errors, no horizontal overflow at 375 px (checked via DOM).
- Bug found and fixed during testing: the search read the HTTP response only up to the first chunk (head and body often arrive separately) and therefore did not find machines reliably.
- Not checked by screenshot: 375 px rendering of the interface (the browser pane was not visible at the time); the structure is the approved mockup, the CSS comes from it.

## Decisions
- **Discovery:** active scan of the /24 network (TCP connection + `GET /api/discovery/hello`), no mDNS. Reason: works in the Docker bridge network without `network_mode: host` and without a new dependency; mDNS would not reach the container in the bridge network (and `network_mode: host` changes ports/firewall: PZ's business). Which network is scanned: (1) the address under which the browser called the page (in Docker that is the host's LAN address, not the container IP), (2) the networks of already known machines, (3) setting `nodes.scan_nets` (CIDR list), (4) only without these: networks of the own interfaces. For development: environment variable `NODES_SCAN_TARGETS` (e.g. `127.0.0.1:8820-8822`), changes nothing in production behavior.
- **Machine list:** `DATA/nodes.json` (mode 600; contains the tokens, which therefore never end up in settings/`/api/state`). `PEERS` is adopted on first start (as "not paired, trusted as before"); addresses newly added to `PEERS` later are added once, but deleted ones are never recreated.
- **Pairing:** request → confirmation on the other machine (with a 6-digit code on both sides) → shared token. Calls between paired machines carry `X-Node-Token`; `auth.py` lets them through even when `AUTH_PASS` is set.

## Interfaces offered
(Provisional, changes only with an announcement here.)

### `/api/state` → `peers[i]` (existing fields stay, new ones added)
```json
{
  "name": "maintux", "url": "http://192.168.178.189:8780", "reachable": true,
  "instance": "maintux", "cores": 32, "load": 4.1, "conv_active": 2, "conv_paused": false, "has_handover": true,
  "conversions": [], "uploads": [], "jobs": [], "drives": [], "output": {}, "now": 1760000000.0,
  "capabilities": {"version": "0.4.0", "features": ["handover"], "nodes": 1, "encoders": ["libx265", "libx264"]},

  "id": "5f0c…",              // instance ID (empty on old machines)
  "trust": "paired",          // "paired" (token) | "legacy" (without token, as before) | "lost" (other side unpaired)
  "legacy": false,            // true = old version without pairing/capability report -> do not rely on capabilities
  "version": "0.4.0",         // "" on old machines
  "mem": 33285996544, "started": 1759900000.0,
  "last_seen": 1760000000.0, "online_since": 1759990000.0
}
```
Run-on selection (PF): `p.reachable && !p.legacy` for new functions; for functions of a v1-compatible job `p.reachable && p.has_handover` is enough. Individual capabilities: `p.capabilities.encoders` etc. (only if `!p.legacy`). In standalone mode `peers` is empty (cluster elements disappear by themselves).

### `/api/state` → `node` (this machine, light; other machines read it too) and `nodemgr` (for the own interface)
```json
"node": {"id": "5f0c…", "name": "vierstein", "mode": "verbund", "discoverable": true, "version": "0.4.0",
         "started": 1759900000.0, "cores": 4, "mem": 7516192768},
"nodemgr": {"nodes": [{"nid": "…", "name": "maintux", "url": "http://…:8780", "id": "…", "trust": "paired|legacy", "origin": "peers|manual|pairing", "added": 1.0, "paired": true}],
            "pairing": {"incoming": [{"rid": "…", "name": "vierstein", "url": "…", "version": "0.4.0", "code": "482913", "age": 20}],
                        "outgoing": [{"rid": "…", "url": "…", "name": "maintux", "code": "482913", "status": "waiting|ok|denied|expired|cancelled", "error": "", "age": 3}]},
            "scan": {"running": true, "done": 187, "total": 254, "nets": ["192.168.178.0/24"], "found": [{"id": "…", "name": "maintux", "url": "…", "version": "0.4.0", "cores": 32, "mem": 1, "self": false, "known": "", "paired": false}], "error": ""},
            "env_peers": false}
```
(`nodemgr.nodes` stays populated in standalone mode as well, `peers` is empty there.)

### Backend for other packages
- `from app import cluster`: `cluster.peer_call(name, "library/convert", {...}, timeout=15.0)` calls a machine from the list with its token (raises on error); proxy `POST /api/peer/{name}/{path}` unchanged (allow list via `ext.allow_proxy`).
- Settings `nodes`: `mode` (`standalone`|`verbund`), `discoverable`, `name`, `public_url`, `scan_nets`, `auto_search`.
- Endpoints (public = reachable without a password, needed before pairing):
  `GET /api/nodes` · `POST /api/nodes/check {url}` (reachable? `legacy`? `known`?) · `POST /api/nodes {url,name?}` (without pairing, old machines only) ·
  `PATCH /api/nodes/{nid} {name}` · `DELETE /api/nodes/{nid}` · `POST /api/nodes/{nid}/unpair` · `POST /api/nodes/{nid}/test`;
  pairing: `POST /api/nodes/pair {url}` -> `{rid, code, name}` · `POST /api/nodes/pair-outgoing/{rid}/cancel` · `POST /api/nodes/pair-incoming/{rid}/accept|deny`;
  between machines: `POST /api/nodes/pair-request` (public) · `GET /api/nodes/pair-poll/{rid}` (public, secret in the header) · `POST /api/nodes/pair-cancel/{rid}` (public) · `POST /api/nodes/unpair` (token) · `GET /api/nodes/whoami` (public; reveals name/ID only with a valid token);
  search: `GET /api/discovery/hello` (public, 404 if not discoverable) · `POST /api/discovery/scan` · `GET /api/discovery/scan` · `POST /api/discovery/scan/cancel`.
- For development: `NODES_SCAN_TARGETS="127.0.0.1:8820-8822"` (host/port list, replaces the network choice), `NODES_SCAN_PORTS`.
- Tokens live only in `DATA/nodes.json` (mode 600), not in the `nodes` namespace (so no `secret` fields are needed).

## Needs from others
- PB: Agreed (coordinator): section `registerSettingsSection({id:'nodes', label:'Rechner', order:30, icon, description, …})`; PB saves per section `collect()` = `{nodes:{name, mode, discoverable, scan_nets, auto_search}}`. The machine list (pair, search, add, rename, remove) is not a form field but calls its own endpoints directly; on changes to controls I trigger `change`. The mockup therefore has no save button of its own. Status: done.
- PZ (optional): in `main.py` the condition `if cluster.parse_peers(PEERS_RAW): create_task(cluster.peer_prober())` can go; the prober now starts via `nodes.py` and runs only once (double start is guarded).
- PZ: Docker/Compose need nothing. Whoever uses discovery in the Docker bridge network enters `nodes.scan_nets` if needed.

## Foreign files touched
(none)

## Questions for the user
1. Should a paired machine require a token even without `AUTH_PASS` (only paired machines may hand over jobs/control drives)? Proposal: no, on an open LAN it stays as before; the token takes effect where `AUTH_PASS` is set and identifies the other side.
2. The own name (`nodes.name`) is displayed and passed on to other machines; lock files and `capacity.instance` keep the host name (INSTANCE_NAME), because `config.INSTANCE` is bound into many modules at import. Is that enough, or should the name apply everywhere (that would need changes in P0 modules)?
3. A pairing request runs for 10 minutes. Is that enough?

## Known limits
- The token travels unencrypted (HTTP) through the LAN when pairing; this protects against foreign calls when `AUTH_PASS` is set, not against eavesdropping on the network. Without `AUTH_PASS` the LAN stays open as before.
- If a machine changes its IP (DHCP), the entry reports `id_mismatch: true` or offline; the address cannot be changed yet (remove and pair again). Can be added as "change address" once the mockup is approved.
- A machine that does not answer the search (old version or not discoverable) can only be added by address.
