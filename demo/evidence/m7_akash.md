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

## Redeploy with the mender (14:46–14:48 PDT, builder-authorized)

- Old deployment 1791578920187 closed FIRST (single writer), then image `eef7d17` (digest sha256:3f266cfd1489…) deployed: dseq **1791582426373**, 8 bids, provider akash1aaul837r7…, ready at 14:47:57.
- Live status page: http://jp4ikhmqk9alt94bi0g5c68d80.ingress.h6i-dedicated.eu-se-1.digitalfrontier.so/status
- First cycle: write mode, sha eef7d17, findings=1, duplicates_skipped=1, issues_created=0, 9.1s; ClickHouse scan_runs host='akash'.

## Redeploy for option C (15:11–15:12 PDT, builder-authorized)

- main branch protected (1 approving review, no force-push/deletion; admin bypass only).
- CWE migration run by the builder in the ClickHouse SQL console ("ALTER succeeded"); worker also runs idempotent migrate-on-start.
- Closed 1791582426373 FIRST, deployed image c37d7a7 (CWE classification, sandbox exploit test, draft human-review PRs on): dseq **1791583925308**, 7 bids, ready 15:12:24.
- Status: http://i1cbkmcl41c2957r09nvn4st0c.ingress.h6i-dedicated.eu-se-1.digitalfrontier.so/status → host=akash, write mode, findings=1, duplicates_skipped=1, errors=0, 8.9s.
