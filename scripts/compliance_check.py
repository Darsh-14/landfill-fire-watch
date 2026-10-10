"""Hackathon compliance checks (CLAUDE.md §10): commit dates, secrets, licence files.

  * every commit (author and committer date) falls between 2026-10-08 and 2026-10-11 (IST)
  * .env is not tracked; the FIRMS key and admin token from .env appear in no tracked file and in no
    commit of the full history (`git log -p` text search, values never printed)
  * LICENSE (Apache-2.0) and data/LICENSE-DATA.md exist
Run gitleaks separately (`make compliance` does both).
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
START, END = date(2026, 10, 8), date(2026, 10, 11)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=True).stdout


def env_secrets() -> dict[str, str]:
    out = {}
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                if k.strip() in ("FIRMS_MAP_KEY", "ADMIN_TOKEN") and v.strip():
                    out[k.strip()] = v.strip()
    return out


def main() -> int:
    ok = True
    rows = git("log", "--all", "--format=%H|%aI|%cI|%s").strip().splitlines()
    bad = []
    for r in rows:
        sha, a, c, subj = r.split("|", 3)
        for label, ts in (("author", a), ("committer", c)):
            d = datetime.fromisoformat(ts).date()
            if not START <= d <= END:
                bad.append(f"{sha[:8]} {label} {ts} {subj[:50]}")
    first = rows[-1].split("|")[1] if rows else None
    print(f"commits: {len(rows)}; first {first}; last {rows[0].split('|')[1] if rows else None}")
    print("commit dates within 2026-10-08..2026-10-11:", "OK" if not bad else "FAIL")
    for b in bad:
        print("   ", b)
    ok &= not bad

    tracked = git("ls-files").splitlines()
    env_tracked = [f for f in tracked if f == ".env" or (f.startswith(".env") and f != ".env.example")]
    print(".env not tracked:", "OK" if not env_tracked else f"FAIL {env_tracked}")
    ok &= not env_tracked

    history = git("log", "--all", "-p", "--no-color")
    for name, value in env_secrets().items():
        in_files = [f for f in tracked if (ROOT / f).is_file() and value.encode() in (ROOT / f).read_bytes()]
        in_hist = value in history
        print(f"{name} absent from tracked files and full history:",
              "OK" if not in_files and not in_hist else f"FAIL files={in_files} history={in_hist}")
        ok &= not in_files and not in_hist

    for f in ("LICENSE", "data/LICENSE-DATA.md"):
        print(f"{f} present:", "OK" if (ROOT / f).exists() else "FAIL")
        ok &= (ROOT / f).exists()
    lic = (ROOT / "LICENSE").read_text(encoding="utf-8")
    print("LICENSE is Apache-2.0:", "OK" if "Apache License" in lic and "Version 2.0" in lic else "FAIL")
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
