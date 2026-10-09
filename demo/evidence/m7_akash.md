# M7 evidence: KaryaShield worker running on Akash Network

- When: 2026-10-09 13:48–13:55 PDT. Builder-authorized ("go 2, deploy").
- Image: ghcr.io/tadinve/karyashield:7e74e5e (public; digest sha256:92c282e43cf8…)
- Deployed with `deploy/akash_deploy.py` via Akash Console API (managed wallet, runtime cap 8h).

```
13:48:34 creating deployment ...
13:48:41 deployment created dseq=1791578920187 tx=9F5758EAD4F38516…
13:48:48 9 bid(s); choosing provider akash1s3hq36mpas4nmkqasn7fgwhs9968cgl3u5esnw at 5.604209000000000000 uact/block
13:48:54 lease created; manifest sent. waiting for the service to come up ...
13:49:32 READY: http://66b8jplb55cjb84lc2qgccvce0.ingress.froggy-servers.com/status
{
  "dseq": "1791578920187",
  "state": "active",
  "leases": [
    {
      "provider": "akash1s3hq36mpas4nmkqasn7fgwhs9968cgl3u5esnw",
      "state": "active",
      "services": {
        "karyashield": {
          "uris": [
            "66b8jplb55cjb84lc2qgccvce0.ingress.froggy-servers.com"
          ],
          "ready": 1,
          "available": 1
        }
      }
    }
  ]
}
```

ClickHouse `scan_runs` row written by the Akash worker (host='akash', write mode, duplicate recognized, no new issue):
```
(2026-10-09 20:49:25 UTC, 'akash', '61b129c48df6', 'write', '7e74e5e0e2e9', findings=1, issues_created=0, duplicates_skipped=1, errors=0, 7.9s)
```

Known issue: the provider ingress (froggy-servers.com) returns its default nginx 404 for our hostname, so the /status page is not reachable yet; the worker itself is running (ClickHouse evidence).

## Autonomous reaction to a new commit

Commit `3517894` pushed at 13:54:50 PDT; the Akash worker scanned it ~25s later with no human action:
```
(2026-10-09 20:55:16 UTC, host=akash, run da5523e88295, sha 35178941fa3f, findings=1, issues_created=0, duplicates_skipped=1, errors=0, 6.7s)
```
