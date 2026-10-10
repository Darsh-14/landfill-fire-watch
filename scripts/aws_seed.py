"""After `sam deploy`: put the replay incidents into DynamoDB and the backtest JSON into S3.

Replays use the same code as `make replay` (cached FIRMS + Open-Meteo archive), with STORE=dynamodb.
Usage: python scripts/aws_seed.py [--events brahmapuram-2023 deonar-2016]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from aws_common import REGION, session, stack_outputs  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", nargs="*", default=["brahmapuram-2023", "deonar-2016", "ghazipur-2022"])
    args = ap.parse_args()
    out = stack_outputs()
    os.environ.update(STORE="dynamodb", TABLE_NAME=out["TableName"], AWS_DEFAULT_REGION=REGION)
    import backtest

    for ev in args.events:
        print(f"replay {ev} -> DynamoDB {out['TableName']}")
        if backtest.replay(ev) != 0:
            return 1
    body = (HERE.parent / "out" / "backtest.json").read_bytes()
    session().client("s3").put_object(Bucket=out["BucketName"], Key="backtest/backtest.json", Body=body,
                                      ContentType="application/json")
    print(f"uploaded out/backtest.json -> s3://{out['BucketName']}/backtest/backtest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
