#!/usr/bin/env python3
"""Verbund-Test mit drei lokalen Instanzen (Paket C). Die Instanzen müssen laufen (frische Datenordner):

  export NODES_SCAN_TARGETS="127.0.0.1:8820-8822"
  scripts/dev.sh start --bg --port 8820 --name dev-c  --peers "dev-c2=http://127.0.0.1:8821"
  scripts/dev.sh start --bg --port 8821 --name dev-c2 --peers "dev-c=http://127.0.0.1:8820"
  DEV_ASGI=main:app DEV_APP_DIR=<ae4603e>/app scripts/dev.sh start --bg --port 8822 --name dev-c3   # alter Stand
  scripts/test-nodes.py

A = 8820 (verbund), B = 8821 (verbund), C = 8822 (alter Stand ae4603e). Der Test ändert die Einstellungen von A und B.
"""
import json
import sys
import time
import urllib.error
import urllib.request

A, B, C = "http://127.0.0.1:8820", "http://127.0.0.1:8821", "http://127.0.0.1:8822"
fails = 0


def call(base, path, body=None, method=None, headers=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **(headers or {})}, method=method or ("POST" if body is not None else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except ValueError:
            return e.code, {}


def check(cond, msg):
    global fails
    print(("ok   " if cond else "FEHLER ") + msg)
    fails += 0 if cond else 1


def state(base):
    return call(base, "/api/state")[1]


def peer(base, name):
    return next((p for p in state(base).get("peers", []) if p["name"] == name), None)


def wait(fn, secs=15):
    t = time.time()
    while time.time() - t < secs:
        v = fn()
        if v:
            return v
        time.sleep(0.5)
    return None


def settings(base, **kw):
    return call(base, "/api/settings", {"nodes": kw})


wait(lambda: call(C, "/api/state")[0] == 200 and call(B, "/api/state")[0] == 200, 30)
# 1. Migration aus PEERS
p = wait(lambda: (peer(A, "dev-c2") or {}).get("reachable") and peer(A, "dev-c2"))
check(p and p["trust"] == "legacy" and not p["legacy"], "A: dev-c2 aus PEERS übernommen, erreichbar, nicht gekoppelt (neue Version)")
check(state(A)["settings"]["nodes"]["mode"] == "verbund", "A: Betriebsart wegen PEERS auf verbund")
check("token" not in json.dumps(state(A)), "A: kein Token in /api/state")

# 2. alter Rechner: prüfen, hinzufügen, Kopplung nicht möglich
s, r = call(A, "/api/nodes/check", {"url": "127.0.0.1:8822"})
check(s == 200 and r["ok"] and r["legacy"], "A: check erkennt C als ältere Version")
s, r = call(A, "/api/nodes/pair", {"url": C})
check(s == 409, "A: Kopplung mit C (alt) abgelehnt: " + str(r.get("detail"))[:60])
s, r = call(A, "/api/nodes", {"url": C, "name": "alt"})
check(s == 200 and r["name"] == "alt", "A: C ohne Kopplung hinzugefügt")
p = wait(lambda: (peer(A, "alt") or {}).get("reachable") and peer(A, "alt"))
check(p and p["legacy"] and p["version"] == "" and p["trust"] == "legacy", "A: C als ältere Version markiert (legacy, ohne Version)")
s, r = call(A, "/api/nodes", {"url": B})
check(s == 409, "A: neue Version nicht ohne Kopplung hinzufügbar (schon in Liste)")

# 3. Suche: B nicht auffindbar, dann auffindbar
settings(B, discoverable=False)
settings(A, discoverable=False)
call(A, "/api/discovery/scan", {})
wait(lambda: not call(A, "/api/discovery/scan")[1]["running"])
sc = call(A, "/api/discovery/scan")[1]
check(not sc["found"] and sc["total"] == 3, f"Suche: nichts gefunden, solange niemand auffindbar ist ({sc['total']} Adressen)")
check(call(B, "/api/discovery/hello")[0] == 404, "hello: 404, wenn nicht auffindbar")
settings(B, discoverable=True)
call(A, "/api/discovery/scan", {})
time.sleep(0.5)
wait(lambda: not call(A, "/api/discovery/scan")[1]["running"])
sc = call(A, "/api/discovery/scan")[1]
check([f["name"] for f in sc["found"]] == ["dev-c2"] and sc["found"][0]["known"] == "dev-c2", "Suche: nur B gefunden (alter Rechner antwortet nicht), als bekannt markiert")
settings(B, discoverable=False)

# 4. Kopplung A -> B mit Bestätigung
s, r = call(A, "/api/nodes/pair", {"url": B})
check(s == 200 and len(r["code"]) == 6, "A: Kopplungsanfrage gesendet")
inc = wait(lambda: state(B)["nodemgr"]["pairing"]["incoming"])
check(inc and inc[0]["code"] == r["code"], "B: Anfrage mit demselben Code sichtbar")
time.sleep(3)
check((peer(A, "dev-c2") or {}).get("trust") == "legacy", "A: bis zur Bestätigung weiter nicht gekoppelt")
s, _ = call(B, f"/api/nodes/pair-incoming/{inc[0]['rid']}/accept", {})
check(s == 200, "B: bestätigt")
check(wait(lambda: (peer(A, "dev-c2") or {}).get("trust") == "paired"), "A: dev-c2 gekoppelt")
check(wait(lambda: (peer(B, "dev-c") or {}).get("trust") == "paired"), "B: dev-c gekoppelt")
time.sleep(14)
check((peer(B, "dev-c") or {}).get("trust") == "paired" and (peer(A, "dev-c2") or {}).get("trust") == "paired", "beide bleiben gekoppelt (kein falsches „gelöst“)")
s, r = call(A, "/api/peer/dev-c2/conversions/pause", {"paused": False})
check(s == 200, "Proxy mit Token funktioniert")
s, r = call(B, "/api/nodes/whoami")
check(r == {"paired": False}, "whoami ohne Token verrät nichts")
tok = json.load(open(sys.argv[1]))["nodes"][0]["token"] if len(sys.argv) > 1 else None
if tok:
    check(call(B, "/api/nodes/whoami", headers={"X-Node-Token": tok})[1].get("paired") is True, "whoami mit Token: gekoppelt")

# 5. Entkoppeln von A: beide Seiten ohne Token
s, nodes = call(A, "/api/nodes")
nid = next(n["nid"] for n in nodes["nodes"] if n["name"] == "dev-c2")
check(call(A, f"/api/nodes/{nid}/unpair", {})[0] == 200, "A: entkoppelt")
check(wait(lambda: (peer(A, "dev-c2") or {}).get("trust") == "legacy") and wait(lambda: (peer(B, "dev-c") or {}).get("trust") == "legacy"),
      "beide Seiten: Token gelöscht, Rechner bleibt in der Liste")

# 6. Ablehnen und Zurückziehen
s, r = call(A, "/api/nodes/pair", {"url": B})
inc = wait(lambda: state(B)["nodemgr"]["pairing"]["incoming"])
call(B, f"/api/nodes/pair-incoming/{inc[0]['rid']}/deny", {})
o = wait(lambda: [x for x in state(A)["nodemgr"]["pairing"]["outgoing"] if x["rid"] == r["rid"] and x["status"] != "waiting"])
check(o and o[0]["status"] == "denied", "Ablehnen kommt bei A an")
s, r = call(A, "/api/nodes/pair", {"url": B})
check(s == 200, "A: neue Anfrage")
call(A, f"/api/nodes/pair-outgoing/{r['rid']}/cancel", {})
check(wait(lambda: not state(B)["nodemgr"]["pairing"]["incoming"]), "Zurückziehen entfernt die Anfrage bei B")

# 7. Koppeln, dann B entfernt A -> A wird benachrichtigt
s, r = call(A, "/api/nodes/pair", {"url": B})
inc = wait(lambda: state(B)["nodemgr"]["pairing"]["incoming"])
call(B, f"/api/nodes/pair-incoming/{inc[0]['rid']}/accept", {})
wait(lambda: (peer(A, "dev-c2") or {}).get("trust") == "paired")
nidB = next(n["nid"] for n in call(B, "/api/nodes")[1]["nodes"] if n["name"] == "dev-c")
call(B, f"/api/nodes/{nidB}", method="DELETE")
check(wait(lambda: (peer(A, "dev-c2") or {}).get("trust") == "legacy"), "A: wurde von B entkoppelt (Token weg)")
check(peer(B, "dev-c") is None, "B: dev-c aus der Liste entfernt")

# 8. Umbenennen, doppelter Name
nid = next(n["nid"] for n in call(A, "/api/nodes")[1]["nodes"] if n["name"] == "alt")
check(call(A, f"/api/nodes/{nid}", {"name": "dev-c2"}, "PATCH")[0] == 409, "Umbenennen auf vergebenen Namen: 409")
check(call(A, f"/api/nodes/{nid}", {"name": "secondtux"}, "PATCH")[0] == 200 and wait(lambda: peer(A, "secondtux") and not peer(A, "alt")), "Umbenennen übernimmt Zustand")

# 9. Eigenständig
settings(A, mode="standalone", discoverable=True)
time.sleep(1.5)
check(state(A)["peers"] == [], "eigenständig: keine Rechner in /api/state")
check(call(A, "/api/discovery/hello")[0] == 404, "eigenständig: nicht auffindbar")
check(call(A, "/api/discovery/scan", {})[0] == 409, "eigenständig: keine Suche")
s, r = call(A, "/api/nodes/pair-request", {"id": "x" * 32, "name": "x", "url": B, "secret": "s" * 20})
check(s == 403, "eigenständig: keine Kopplungsanfragen")
check(len(state(A)["nodemgr"]["nodes"]) == 2, "eigenständig: Liste bleibt gespeichert")
settings(A, mode="verbund")
check(wait(lambda: (peer(A, "dev-c2") or {}).get("reachable")), "zurück im Verbund: Rechner wieder da")

print("\nFehler:", fails)
sys.exit(1 if fails else 0)
