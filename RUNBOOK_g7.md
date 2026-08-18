# Load Test Runbook — g7.2xlarge (RTX PRO 4500 32GB)

Instructions for running the load test on a g7 instance. The method, shapes and
rates are identical to RUNBOOK.md / TEST_PLAN.md / config/; this file only covers
what differs for g7. Read RUNBOOK.md first.

## Target instance (differences from RUNBOOK.md)

Set these before running:

| Variable | Meaning |
|---|---|
| `AWS_PROFILE` | AWS profile with SSM access |
| `BENCH_REGION_G7` | region of the g7 instance (default us-west-2) |
| `BENCH_INSTANCE_ID_G7` | g7 instance id |

- Instance type: g7.2xlarge
- GPU: NVIDIA RTX PRO 4500 32GB x1
- **Spot instance**: it can be interrupted. If SSM goes Offline, or
  describe-instances reports terminated, record that in the progress log and
  stop. Do not request a replacement.

## Prerequisites

- Setup (venv + vllm 0.25.1 + ninja + Qwen/Qwen3.5-4B download) should already
  have been run over SSM. Confirm completion via /home/ubuntu/pip_install.log
  and model_dl.log, and wait if it is unfinished.
- The vLLM server is not running. Start it with:

  ```
  sudo -u ubuntu bash -c "cd /home/ubuntu && export PATH=/home/ubuntu/vllm-env/bin:\$PATH && setsid nohup vllm serve Qwen/Qwen3.5-4B --language-model-only --reasoning-parser qwen3 --enable-prefix-caching --max-model-len 65536 > /home/ubuntu/vllm_serve.log 2>&1 < /dev/null &"
  ```

## Important: the 32GB GPU memory limit

- After roughly 9GB of model weights, only about 20GB is left for the KV cache.
  The default max_model_len (262144) very likely will not start, so start with
  `--max-model-len 65536` from the outset. That is the smallest power of two
  that fits the in50000 shapes (50,000 input + 2,000 output).
- If it still fails to start with OOM, try
  `--max-model-len 65536 --gpu-memory-utilization 0.95`. If that also fails,
  skip the nine in50000 shapes, run only the 18 in5000/in10000 shapes with
  `--max-model-len 16384`, and record that decision.
- On a successful start, record the "GPU KV cache size" line (token count) from
  vllm_serve.log into progress.log. It matters as a record of how conditions
  differ from P5.

## Where results go (kept separate from P5)

- Local: `results_g7/`
- Progress log: `results_g7/progress.log`
- Summary: `results_g7/summary.json`
- Primary output on the instance: `/home/ubuntu/bench_results/`

## Other notes

- The test content, saturation rule, completion criteria and prohibitions all
  follow RUNBOOK.md.
- Because the KV cache is small, preemption starts earlier than on P5 as
  concurrent requests grow. Early saturation is expected behaviour; just record
  it.
- The P5 test may be running in parallel in another process. It targets a
  different instance so there is no interference. Do not touch the P5 files
  (`results/`).
