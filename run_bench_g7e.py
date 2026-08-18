#!/usr/bin/env python3
"""Load test driver for g7e.2xlarge (RTX PRO 6000 96GB, spot).

Runs run_bench.py with the target instance, region and output directory
swapped out. Per RUNBOOK_g7e.md:
- Results go to results_g7e/
- On spot interruption (the instance is no longer running), record it in
  progress.log and exit without requesting a replacement
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import run_bench as rb

# g7e-specific overrides (RUNBOOK_g7e.md)
rb.REGION = os.environ.get("BENCH_REGION_G7E", "us-east-2")
rb.INSTANCE_ID = os.environ.get("BENCH_INSTANCE_ID_G7E", "")
rb.LOCAL_RESULTS = Path(__file__).parent / "results_g7e"
rb.PROGRESS_LOG = rb.LOCAL_RESULTS / "progress.log"


def _instance_state() -> str:
    try:
        out = rb.aws([
            "ec2", "describe-instances",
            "--instance-ids", rb.INSTANCE_ID,
            "--query", "Reservations[0].Instances[0].State.Name",
            "--output", "text",
        ])
        return out.strip()
    except RuntimeError as e:
        return f"unknown ({e})"


# RUNBOOK_g7e: check the instance state at least every 5 minutes while waiting,
# and if it is terminated, record it in the progress log and exit immediately
_orig_ssm_wait = rb.ssm_wait
_STATE_CHECK_INTERVAL = 300  # 5 min


def ssm_wait_with_spot_check(command_id: str, max_wait: int):
    import time as _time
    waited = 0
    last_state_check = 0
    while waited <= max_wait:
        step = min(rb.POLL_INTERVAL, max_wait - waited) or rb.POLL_INTERVAL
        _time.sleep(step)
        waited += step
        if waited - last_state_check >= _STATE_CHECK_INTERVAL:
            last_state_check = waited
            state = _instance_state()
            if state not in ("running",) and not state.startswith("unknown"):
                rb.log(
                    f"!!! spot instance is state={state} (detected while waiting). "
                    "Per RUNBOOK_g7e.md, stopping without requesting a replacement."
                )
                sys.exit(2)
        try:
            out = rb.aws([
                "ssm", "get-command-invocation",
                "--command-id", command_id,
                "--instance-id", rb.INSTANCE_ID,
                "--output", "json",
            ])
        except RuntimeError:
            continue
        import json as _json
        inv = _json.loads(out)
        status = inv["Status"]
        if status not in ("Pending", "InProgress", "Delayed"):
            return status, inv.get("StandardOutputContent", ""), inv.get("StandardErrorContent", "")
    return "LocalTimeout", "", ""


rb.ssm_wait = ssm_wait_with_spot_check

_orig_run_bench = rb.run_bench


def run_bench_with_spot_check(shape, rate):
    """On a failed run, check for spot interruption and exit immediately if so."""
    result = _orig_run_bench(shape, rate)
    if result is None:
        try:
            out = rb.aws([
                "ec2", "describe-instances",
                "--instance-ids", rb.INSTANCE_ID,
                "--query", "Reservations[0].Instances[0].State.Name",
                "--output", "text",
            ])
            state = out.strip()
        except RuntimeError as e:
            state = f"unknown ({e})"
        if state != "running":
            rb.log(
                f"!!! spot instance is state={state}. "
                "Per RUNBOOK_g7e.md, stopping without requesting a replacement."
            )
            sys.exit(2)
    return result


rb.run_bench = run_bench_with_spot_check

if __name__ == "__main__":
    rb.main()
