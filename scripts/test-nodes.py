#!/usr/bin/env python3
"""Cluster test with three local instances (package C). The instances must be running (fresh data folders):

  export NODES_SCAN_TARGETS="127.0.0.1:8820-8822"
  scripts/dev.sh start --bg --port 8820 --name dev-c  --peers "dev-c2=http://127.0.0.1:8821"
  scripts/dev.sh start --bg --port 8821 --name dev-c2 --peers "dev-c=http://127.0.0.1:8820"
  DEV_ASGI=main:app DEV_APP_DIR=<ae4603e>/app scripts/dev.sh start --bg --port 8822 --name dev-c3   # old version
  scripts/test-nodes.py

A = 8820 (cluster), B = 8821 (cluster), C = 8822 (old version ae4603e). The test changes the settings of A and B.
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
    print(("ok    " if cond else "ERROR ") + msg)
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
# 1. migration from PEERS
p = wait(lambda: (peer(A, "dev-c2") or {}).get("reachable") and peer(A, "dev-c2"))
check(p and p["trust"] == "legacy" and not p["legacy"], "A: dev-c2 taken over from PEERS, reachable, not paired (new version)")
check(state(A)["settings"]["nodes"]["mode"] == "verbund", "A: mode set to cluster because of PEERS")
check("token" not in json.dumps(state(A)), "A: no token in /api/state")

# 2. old machine: check, add, pairing not possible
s, r = call(A, "/api/nodes/check", {"url": "127.0.0.1:8822"})
check(s == 200 and r["ok"] and r["legacy"], "A: check recognizes C as an older version")
s, r = call(A, "/api/nodes/pair", {"url": C})
check(s == 409, "A: pairing with C (old) refused: " + str(r.get("detail"))[:60])
s, r = call(A, "/api/nodes", {"url": C, "name": "old"})
check(s == 200 and r["name"] == "old", "A: C added without pairing")
p = wait(lambda: (peer(A, "old") or {}).get("reachable") and peer(A, "old"))
check(p and p["legacy"] and p["version"] == "" and p["trust"] == "legacy", "A: C marked as an older version (legacy, without version)")
s, r = call(A, "/api/nodes", {"url": B})
check(s == 409, "A: new version cannot be added without pairing (already in the list)")

# 3. search: in cluster mode every machine is always discoverable
check(call(B, "/api/discovery/hello")[0] == 200, "hello: B always answers in cluster mode")
call(A, "/api/discovery/scan", {})
time.sleep(0.5)
wait(lambda: not call(A, "/api/discovery/scan")[1]["running"])
sc = call(A, "/api/discovery/scan")[1]
check([f["name"] for f in sc["found"]] == ["dev-c2"] and sc["found"][0]["known"] == "dev-c2", "search: only B found (the old machine does not answer), marked as known")

# 3b. pairing is optional: without the requirement B can be added directly, with it not
nidB = next(n["nid"] for n in call(A, "/api/nodes")[1]["nodes"] if n["name"] == "dev-c2")
call(A, f"/api/nodes/{nidB}", method="DELETE")
settings(A, pairing_required=True)
check(call(A, "/api/nodes", {"url": B})[0] == 409, "A: with pairing required no direct adding")
settings(A, pairing_required=False)
s, r = call(A, "/api/nodes", {"url": B})
check(s == 200 and r["name"] == "dev-c2" and not r["paired"], "A: without the requirement B added directly")
check(wait(lambda: (peer(A, "dev-c2") or {}).get("reachable")), "A: directly added machine reachable")

# 4. pairing A -> B with confirmation
s, r = call(A, "/api/nodes/pair", {"url": B})
check(s == 200 and len(r["code"]) == 6, "A: pairing request sent")
inc = wait(lambda: state(B)["nodemgr"]["pairing"]["incoming"])
check(inc and inc[0]["code"] == r["code"], "B: request visible with the same code")
time.sleep(3)
check((peer(A, "dev-c2") or {}).get("trust") == "legacy", "A: still not paired until confirmed")
s, _ = call(B, f"/api/nodes/pair-incoming/{inc[0]['rid']}/accept", {})
check(s == 200, "B: confirmed")
check(wait(lambda: (peer(A, "dev-c2") or {}).get("trust") == "paired"), "A: dev-c2 paired")
check(wait(lambda: (peer(B, "dev-c") or {}).get("trust") == "paired"), "B: dev-c paired")
time.sleep(14)
check((peer(B, "dev-c") or {}).get("trust") == "paired" and (peer(A, "dev-c2") or {}).get("trust") == "paired", "both stay paired (no false \"dissolved\")")
s, r = call(A, "/api/peer/dev-c2/conversions/pause", {"paused": False})
check(s == 200, "proxy with token works")
s, r = call(B, "/api/nodes/whoami")
check(r == {"paired": False}, "whoami without a token reveals nothing")
tok = json.load(open(sys.argv[1]))["nodes"][0]["token"] if len(sys.argv) > 1 else None
if tok:
    check(call(B, "/api/nodes/whoami", headers={"X-Node-Token": tok})[1].get("paired") is True, "whoami with token: paired")

# 5. unpairing from A: both sides without a token
s, nodes = call(A, "/api/nodes")
nid = next(n["nid"] for n in nodes["nodes"] if n["name"] == "dev-c2")
check(call(A, f"/api/nodes/{nid}/unpair", {})[0] == 200, "A: unpaired")
check(wait(lambda: (peer(A, "dev-c2") or {}).get("trust") == "legacy") and wait(lambda: (peer(B, "dev-c") or {}).get("trust") == "legacy"),
      "both sides: token deleted, the machine stays in the list")

# 6. declining and withdrawing
s, r = call(A, "/api/nodes/pair", {"url": B})
inc = wait(lambda: state(B)["nodemgr"]["pairing"]["incoming"])
call(B, f"/api/nodes/pair-incoming/{inc[0]['rid']}/deny", {})
o = wait(lambda: [x for x in state(A)["nodemgr"]["pairing"]["outgoing"] if x["rid"] == r["rid"] and x["status"] != "waiting"])
check(o and o[0]["status"] == "denied", "declining reaches A")
s, r = call(A, "/api/nodes/pair", {"url": B})
check(s == 200, "A: new request")
call(A, f"/api/nodes/pair-outgoing/{r['rid']}/cancel", {})
check(wait(lambda: not state(B)["nodemgr"]["pairing"]["incoming"]), "withdrawing removes the request on B")

# 7. pair, then B removes A -> A is notified
s, r = call(A, "/api/nodes/pair", {"url": B})
inc = wait(lambda: state(B)["nodemgr"]["pairing"]["incoming"])
call(B, f"/api/nodes/pair-incoming/{inc[0]['rid']}/accept", {})
wait(lambda: (peer(A, "dev-c2") or {}).get("trust") == "paired")
nidB = next(n["nid"] for n in call(B, "/api/nodes")[1]["nodes"] if n["name"] == "dev-c")
call(B, f"/api/nodes/{nidB}", method="DELETE")
check(wait(lambda: (peer(A, "dev-c2") or {}).get("trust") == "legacy"), "A: was unpaired by B (token gone)")
check(peer(B, "dev-c") is None, "B: dev-c removed from the list")

# 8. renaming, duplicate name
nid = next(n["nid"] for n in call(A, "/api/nodes")[1]["nodes"] if n["name"] == "old")
check(call(A, f"/api/nodes/{nid}", {"name": "dev-c2"}, "PATCH")[0] == 409, "renaming to a name that is taken: 409")
check(call(A, f"/api/nodes/{nid}", {"name": "secondtux"}, "PATCH")[0] == 200 and wait(lambda: peer(A, "secondtux") and not peer(A, "old")), "renaming keeps the state")

# 9. standalone
settings(A, mode="standalone")
time.sleep(1.5)
check(state(A)["peers"] == [], "standalone: no machines in /api/state")
check(call(A, "/api/discovery/hello")[0] == 404, "standalone: not discoverable (always on only in cluster mode)")
check(call(A, "/api/discovery/scan", {})[0] == 409, "standalone: no search")
s, r = call(A, "/api/nodes/pair-request", {"id": "x" * 32, "name": "x", "url": B, "secret": "s" * 20})
check(s == 403, "standalone: no pairing requests")
check(len(state(A)["nodemgr"]["nodes"]) == 2, "standalone: the list stays saved")
settings(A, mode="verbund")
check(wait(lambda: (peer(A, "dev-c2") or {}).get("reachable")), "back in cluster mode: machines are back")

print("\nErrors:", fails)
sys.exit(1 if fails else 0)
