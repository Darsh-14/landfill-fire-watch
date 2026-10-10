"""Write the two SecureString parameters from .env to SSM without printing them.

  /lfw/firms_map_key  <- FIRMS_MAP_KEY in .env
  /lfw/admin_token    <- ADMIN_TOKEN in .env (generated and written to .env if empty)

Usage: python scripts/aws_put_params.py [--overwrite]
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aws_common import REGION, session  # noqa: E402

ENV = Path(__file__).resolve().parent.parent / ".env"


def read_env() -> dict[str, str]:
    out = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    env = read_env()
    if not env.get("FIRMS_MAP_KEY"):
        print("FIRMS_MAP_KEY is empty in .env")
        return 2
    if not env.get("ADMIN_TOKEN"):
        token = secrets.token_urlsafe(32)
        with ENV.open("a", encoding="utf-8", newline="\n") as f:
            f.write(f"\nADMIN_TOKEN={token}\n")
        env["ADMIN_TOKEN"] = token
        print("Generated a new ADMIN_TOKEN and saved it to .env (not printed).")
    ssm = session().client("ssm")
    for name, key in (("/lfw/firms_map_key", "FIRMS_MAP_KEY"), ("/lfw/admin_token", "ADMIN_TOKEN")):
        ssm.put_parameter(Name=name, Value=env[key], Type="SecureString", Overwrite=args.overwrite)
        print(f"wrote {name} (SecureString, {REGION})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
