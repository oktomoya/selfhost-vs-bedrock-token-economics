#!/usr/bin/env python3
"""Load test driver for g7.2xlarge (RTX PRO 4500 32GB, spot).

Runs run_bench.py with the target instance, region and output directory
swapped out. Per RUNBOOK_g7.md:
- Results go to results_g7/
- On spot interruption (the instance is no longer running), record it in
  progress.log and exit without requesting a replacement
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import run_bench as rb

# g7-specific overrides (RUNBOOK_g7.md)
rb.REGION = os.environ.get("BENCH_REGION_G7", "us-west-2")
rb.INSTANCE_ID = os.environ.get("BENCH_INSTANCE_ID_G7", "")
rb.LOCAL_RESULTS = Path(__file__).parent / "results_g7"
rb.PROGRESS_LOG = rb.LOCAL_RESULTS / "progress.log"

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
                "Per RUNBOOK_g7.md, stopping without requesting a replacement."
            )
            sys.exit(2)
    return result


rb.run_bench = run_bench_with_spot_check

if __name__ == "__main__":
    rb.main()
