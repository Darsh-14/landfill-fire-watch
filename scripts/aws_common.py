"""Helpers for the AWS scripts: stack outputs and region. Uses your local AWS credentials."""

from __future__ import annotations

import os

STACK = os.environ.get("LFW_STACK", "landfill-fire-watch")
REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "ap-south-1"


def session():
    import boto3

    return boto3.session.Session(region_name=REGION)


def stack_outputs(stack: str = STACK) -> dict[str, str]:
    cfn = session().client("cloudformation")
    st = cfn.describe_stacks(StackName=stack)["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in st.get("Outputs", [])}
