#!/usr/bin/env python3
"""Driver that sweeps `vllm bench serve` over shapes x rates via SSM.

Based on RUNBOOK.md / TEST_PLAN.md / config/.
- For each shape (config.SHAPES), sweep REQUEST_RATES in ascending order
- Saturated when measured request_throughput < rate * 0.80, then move on
- Each run is cut off after a 20 minute timeout
- Result JSON is pulled into the local results/, with progress.log appended as it goes

Note: for vllm bench serve, total input = random-input-len + random-prefix-len.
To match the intent in config (total input = input_tokens), random_tokens is
passed as --random-input-len.
"""

import json
import os
import subprocess
import sys
import time
import zlib
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config

PROFILE = os.environ.get("AWS_PROFILE", "")
REGION = os.environ.get("BENCH_REGION", "")
INSTANCE_ID = config.INSTANCE["instance_id"]
REMOTE_DIR = "/home/ubuntu/bench_results"
LOCAL_RESULTS = Path(__file__).parent / "results"
PROGRESS_LOG = LOCAL_RESULTS / "progress.log"
RUN_TIMEOUT_SEC = 20 * 60  # RUNBOOK: 20 minute cap per run
POLL_INTERVAL = 20


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(PROGRESS_LOG, "a") as f:
        f.write(line + "\n")


def aws(args: list, retries: int = 3):
    """Run the aws cli with retries. Returns stdout."""
    cmd = ["aws", "--profile", PROFILE, "--region", REGION] + args
    last_err = None
    for _ in range(retries):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                return r.stdout
            last_err = r.stderr.strip()
        except subprocess.TimeoutExpired as e:
            last_err = f"cli timeout: {e}"
        time.sleep(10)
    raise RuntimeError(f"aws cli failed: {last_err}")


def ssm_run(commands: list, exec_timeout: int):
    payload = json.dumps({"commands": commands, "executionTimeout": [str(exec_timeout)]})
    out = aws([
        "ssm", "send-command",
        "--instance-ids", INSTANCE_ID,
        "--document-name", "AWS-RunShellScript",
        "--parameters", payload,
        "--query", "Command.CommandId", "--output", "text",
    ])
    return out.strip()


def ssm_wait(command_id: str, max_wait: int):
    """Poll until completion. Returns (status, stdout, stderr)."""
    waited = 0
    while waited <= max_wait:
        time.sleep(POLL_INTERVAL)
        waited += POLL_INTERVAL
        try:
            out = aws([
                "ssm", "get-command-invocation",
                "--command-id", command_id,
                "--instance-id", INSTANCE_ID,
                "--output", "json",
            ])
        except RuntimeError:
            continue
        inv = json.loads(out)
        status = inv["Status"]
        if status not in ("Pending", "InProgress", "Delayed"):
            return status, inv.get("StandardOutputContent", ""), inv.get("StandardErrorContent", "")
    return "LocalTimeout", "", ""


def run_bench(shape: dict, rate: float) -> dict | None:
    """A single run. Returns the result dict (JSON content), or None on failure."""
    name = shape["name"]
    num_prompts = config.num_prompts_for(rate)
    fname = f"{name}_rate{rate}.json"
    # Unique seed per run. With the default seed=0, prompts from the previous run
    # stay in the prefix cache and break the intended cache ratio.
    seed = zlib.crc32(fname.encode()) % 100000
    bench_cmd = (
        "cd /home/ubuntu && PATH=/home/ubuntu/vllm-env/bin:$PATH "
        "vllm bench serve "
        f"--model Qwen/Qwen3.5-4B --base-url http://localhost:8000 "
        f"--dataset-name random "
        f"--random-input-len {shape['random_tokens']} "
        f"--random-output-len {shape['output_tokens']} "
        f"--random-prefix-len {shape['prefix_tokens']} "
        f"--request-rate {rate} --num-prompts {num_prompts} --seed {seed} "
        f"--ignore-eos --save-result --result-dir {REMOTE_DIR} "
        f"--result-filename {fname}"
    )
    remote = f"sudo -u ubuntu bash -c '{bench_cmd}' 2>&1 | tail -5"
    cid = ssm_run([remote], RUN_TIMEOUT_SEC)
    status, out, err = ssm_wait(cid, RUN_TIMEOUT_SEC + 120)
    if status != "Success":
        log(f"{name} rate={rate}: RUN {status} (aborted) stderr_tail={err[-200:]!r}")
        return None

    # Pull the result JSON
    cid2 = ssm_run([f"cat {REMOTE_DIR}/{fname}"], 60)
    status2, out2, _ = ssm_wait(cid2, 180)
    if status2 != "Success" or not out2.strip():
        log(f"{name} rate={rate}: failed to retrieve result JSON ({status2})")
        return None
    try:
        data = json.loads(out2)
    except json.JSONDecodeError:
        log(f"{name} rate={rate}: JSON parse failed")
        return None

    # Attach the shape parameters and save locally
    data["shape"] = {
        "name": name,
        "input_tokens": shape["input_tokens"],
        "output_tokens": shape["output_tokens"],
        "cache_ratio": shape["cache_ratio"],
        "prefix_tokens": shape["prefix_tokens"],
        "random_tokens": shape["random_tokens"],
    }
    (LOCAL_RESULTS / fname).write_text(json.dumps(data, indent=1))
    return data


def main():
    LOCAL_RESULTS.mkdir(exist_ok=True)
    threshold = config.SATURATION_TRACKING_THRESHOLD
    summary = {}
    t0 = time.time()
    log(f"=== sweep start: {len(config.SHAPES)} shapes x rates {config.REQUEST_RATES} ===")

    for i, shape in enumerate(config.SHAPES, 1):
        name = shape["name"]
        log(f"--- shape {i}/{len(config.SHAPES)}: {name} ---")
        last_ok = None
        sat_info = None
        aborted = None
        for rate in config.REQUEST_RATES:
            fname = f"{name}_rate{rate}.json"
            local = LOCAL_RESULTS / fname
            if local.exists():
                data = json.loads(local.read_text())
                log(f"{name} rate={rate}: reusing existing result")
            else:
                data = run_bench(shape, rate)
            if data is None:
                aborted = f"run failed or timed out at rate={rate}"
                break
            meas = data["request_throughput"]
            saturated = meas < rate * threshold
            log(
                f"{name} rate={rate}: measured {meas:.3f} rps, "
                f"total {data['total_token_throughput']:.0f} tok/s, "
                f"out {data['output_throughput']:.0f} tok/s, "
                f"TTFT mean {data['mean_ttft_ms']:.0f}ms/p99 {data['p99_ttft_ms']:.0f}ms, "
                f"saturated={'YES' if saturated else 'no'}"
            )
            if saturated:
                sat_info = {"saturation_rate": rate, "measured_rps": meas}
                break
            last_ok = (rate, data)

        entry = {"shape": {k: shape[k] for k in ("name", "input_tokens", "output_tokens", "cache_ratio", "prefix_tokens")}}
        if last_ok:
            rate, d = last_ok
            entry["last_unsaturated_rate"] = rate
            entry["measured_rps"] = d["request_throughput"]
            entry["total_token_throughput"] = d["total_token_throughput"]
            entry["output_throughput"] = d["output_throughput"]
            entry["mean_ttft_ms"] = d["mean_ttft_ms"]
            entry["p99_ttft_ms"] = d["p99_ttft_ms"]
            entry["mean_itl_ms"] = d["mean_itl_ms"]
            entry["p99_itl_ms"] = d["p99_itl_ms"]
            entry["mean_tpot_ms"] = d["mean_tpot_ms"]
            entry["p99_tpot_ms"] = d["p99_tpot_ms"]
            entry["duration"] = d["duration"]
            entry["num_prompts"] = d["num_prompts"]
        if sat_info:
            entry["saturated_at"] = sat_info
        if aborted:
            entry["aborted"] = aborted
        if not sat_info and not aborted:
            entry["note"] = "did not saturate up to the highest rate"
        summary[name] = entry
        (LOCAL_RESULTS / "summary.json").write_text(json.dumps(summary, indent=1))

    log(f"=== all shapes complete in {(time.time()-t0)/3600:.2f} hours ===")


if __name__ == "__main__":
    main()
