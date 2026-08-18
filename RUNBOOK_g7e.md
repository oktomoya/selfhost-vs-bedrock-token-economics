# Load Test Runbook — g7e.2xlarge (RTX PRO 6000 96GB)

Instructions for running the load test on a g7e instance. The method, shapes and
rates are identical to RUNBOOK.md / TEST_PLAN.md / config/; this file only covers
what differs for g7e. Read RUNBOOK.md first.

## Target instance (differences from RUNBOOK.md)

Set these before running:

| Variable | Meaning |
|---|---|
| `AWS_PROFILE` | AWS profile with SSM access |
| `BENCH_REGION_G7E` | region of the g7e instance (default us-east-2) |
| `BENCH_INSTANCE_ID_G7E` | g7e instance id |

- Instance type: g7e.2xlarge
- GPU: NVIDIA RTX PRO 6000 Server 96GB x1
- **Spot instance**: it can be interrupted. If SSM goes Offline, or
  describe-instances reports terminated, record that in the progress log and
  stop. Do not request a replacement.
- **Stricter interruption detection**: while waiting for the driver process or
  an SSM command to finish, keep each wait cycle to at most 5 minutes and check
  the instance state with describe-instances every cycle. If terminated is
  detected, record it in the progress log and exit immediately.

## Prerequisites

- Setup (venv + vllm 0.25.1 + ninja + Qwen/Qwen3.5-4B download) should already
  have been run over SSM. Confirm completion via /home/ubuntu/pip_install.log
  and model_dl.log, and wait if it is unfinished.
- The vLLM server is not running. Start it with the text-only configuration,
  the same as P5:

  ```
  sudo -u ubuntu bash -c "cd /home/ubuntu && export PATH=/home/ubuntu/vllm-env/bin:\$PATH && setsid nohup vllm serve Qwen/Qwen3.5-4B --language-model-only --reasoning-parser qwen3 --enable-prefix-caching > /home/ubuntu/vllm_serve.log 2>&1 < /dev/null &"
  ```

- Wait 3 to 5 minutes after starting, confirm health returns 200 and that
  /v1/chat/completions responds, then begin the sweep. If startup fails, check
  vllm_serve.log for the EngineCore error (without the venv on PATH it fails
  because ninja is not found).

## Where results go (kept separate from P5)

- Local: `results_g7e/`
- Progress log: `results_g7e/progress.log`
- Summary: `results_g7e/summary.json`
- Primary output on the instance: `/home/ubuntu/bench_results/`

## Other notes

- With a 96GB GPU, the default max_model_len of 262144 is expected to work, the
  same as P5.
- The test content, saturation rule, completion criteria and prohibitions all
  follow RUNBOOK.md.
- The P5 test may be running in parallel in another process. It targets a
  different instance so there is no interference. Do not touch the P5 files
  (`results/`).
