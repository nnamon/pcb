"""Runs one of review 9's probe scripts and fails if it exits non-zero or prints any line starting with FAIL.
The probes print PASS or FAIL per case; this turns that into an exit status for the suite.

Usage: python3 expect_pass.py script.py args...
"""
import subprocess
import sys

r = subprocess.run([sys.executable, *sys.argv[1:]], capture_output=True, text=True)
sys.stdout.write(r.stdout[-6000:])
sys.stderr.write(r.stderr[-3000:])
bad = [ln for ln in r.stdout.splitlines() if ln.startswith("FAIL")]
sys.exit(1 if r.returncode or bad or "PASS" not in r.stdout else 0)
