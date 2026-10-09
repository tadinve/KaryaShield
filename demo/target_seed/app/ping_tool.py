# INTENTIONALLY VULNERABLE TEST FIXTURE - never execute or deploy.
# Seeded for the KaryaShield static-analysis demo.
import subprocess


def ping_host(host):
    # BAD: user-controlled host is interpolated into a shell command.
    return subprocess.run(f"ping -c 1 {host}", shell=True, capture_output=True)
