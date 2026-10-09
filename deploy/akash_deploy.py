"""Deploy / inspect / close the KaryaShield worker on Akash via the Akash Console API (managed wallet).

Usage (AKASH_API_KEY in .env or the environment):
  python deploy/akash_deploy.py deploy deploy/akash.sdl.local.yaml [--hours 8]
  python deploy/akash_deploy.py status <dseq>
  python deploy/akash_deploy.py close <dseq>

Spends Akash credits: run only with builder authorization. Never prints SDL contents or secrets.
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://console-api.akash.network"
try:  # python.org macOS builds ship no root CAs
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL = ssl.create_default_context()


def _key() -> str:
    key = os.getenv("AKASH_API_KEY", "")
    if not key:
        env = Path(__file__).resolve().parent.parent / ".env"
        for line in env.read_text().splitlines() if env.exists() else []:
            if line.startswith("AKASH_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        sys.exit("AKASH_API_KEY not set")
    return key


def call(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"x-api-key": _key(), "Content-Type": "application/json",
                                          "Accept": "application/json",
                                          "User-Agent": "karyashield-deploy/1.0 (+https://github.com/tadinve/KaryaShield)"})
    try:
        with urllib.request.urlopen(req, timeout=60, context=_SSL) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} -> HTTP {e.code}: {e.read().decode()[:500]}")


def _log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def status(dseq: str) -> dict:
    d = call("GET", f"/v1/deployments/{dseq}")["data"]
    out = {"dseq": dseq, "state": d["deployment"]["state"], "leases": []}
    for lease in d.get("leases", []):
        st = lease.get("status") or {}
        services = {name: {"uris": s.get("uris"), "ready": s.get("ready_replicas"), "available": s.get("available")}
                    for name, s in (st.get("services") or {}).items()}
        out["leases"].append({"provider": lease["id"]["provider"], "state": lease.get("state"), "services": services})
    return out


def deploy(sdl_path: str, hours: int) -> None:
    sdl = Path(sdl_path).read_text()
    if "REPLACE" in sdl:
        sys.exit("SDL still contains REPLACE placeholders; fill them first")
    _log("creating deployment ...")
    created = call("POST", "/v1/deployments",
                   {"data": {"sdl": sdl, "name": "karyashield-worker", "runtimeLimitHours": hours}})["data"]
    dseq = created["dseq"]
    _log(f"deployment created dseq={dseq} tx={created['signTx']['transactionHash'][:16]}…")

    bids = []
    for _ in range(30):  # ~60s
        time.sleep(2)
        bids = [b["bid"] for b in call("GET", f"/v1/bids?dseq={dseq}").get("data", [])
                if b["bid"].get("state") == "open"]
        if len(bids) >= 3:
            break
    if not bids:
        sys.exit(f"no bids received for dseq={dseq}; close it with: close {dseq}")
    best = min(bids, key=lambda b: float(b["price"]["amount"]))
    _log(f"{len(bids)} bid(s); choosing provider {best['id']['provider']} "
         f"at {best['price']['amount']} {best['price']['denom']}/block")

    bid_id = best["id"]
    call("POST", "/v1/leases", {"leases": [{"dseq": dseq, "gseq": bid_id["gseq"], "oseq": bid_id["oseq"],
                                            "provider": bid_id["provider"]}]})
    _log("lease created; manifest sent. waiting for the service to come up ...")
    for _ in range(60):  # ~5 min
        time.sleep(5)
        st = status(dseq)
        svc = (st["leases"][0]["services"].get("karyashield") if st["leases"] else None) or {}
        if svc.get("ready") and svc.get("uris"):
            _log(f"READY: http://{svc['uris'][0]}/status")
            print(json.dumps(st, indent=2))
            return
    _log("service not ready yet; check later with: status " + dseq)
    print(json.dumps(status(dseq), indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("deploy"); d.add_argument("sdl"); d.add_argument("--hours", type=int, default=8)
    s = sub.add_parser("status"); s.add_argument("dseq")
    c = sub.add_parser("close"); c.add_argument("dseq")
    a = ap.parse_args()
    if a.cmd == "deploy":
        deploy(a.sdl, a.hours)
    elif a.cmd == "status":
        print(json.dumps(status(a.dseq), indent=2))
    else:
        call("DELETE", f"/v1/deployments/{a.dseq}")
        _log(f"closed dseq={a.dseq}")


if __name__ == "__main__":
    main()
