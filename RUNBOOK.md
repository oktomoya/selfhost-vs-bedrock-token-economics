# Load Test Runbook

This file is the instruction sheet for whoever (or whatever) runs the load test.
The test plan is TEST_PLAN.md and the parameters live in the `config/` package
(Python). Read both before starting.

## Environment

Set these environment variables before running; nothing is hardcoded:

| Variable | Meaning |
|---|---|
| `AWS_PROFILE` | AWS profile with SSM access to the instance |
| `BENCH_REGION` | region of the target instance |
| `BENCH_INSTANCE_ID` | target instance id |

- Target: an EC2 p5.4xlarge (H100 x1)
- Access: over SSM only (no SSH)
  - Send: `aws ssm send-command --profile "$AWS_PROFILE" --region "$BENCH_REGION" --instance-ids "$BENCH_INSTANCE_ID" --document-name AWS-RunShellScript --parameters 'commands=[...]'`
  - Fetch: `aws ssm get-command-invocation --profile "$AWS_PROFILE" --region "$BENCH_REGION" --command-id <ID> --instance-id "$BENCH_INSTANCE_ID"`
- The vLLM server should already be running on localhost:8000
  (Qwen/Qwen3.5-4B, text-only, prefix caching enabled), so no restart is needed.
  Health check: `curl -s http://localhost:8000/health`
- Important: when running the vllm command on the instance, always prefix it
  with `PATH=/home/ubuntu/vllm-env/bin:$PATH`, otherwise it fails because
  `ninja` is not found. Run the benchmark as the ubuntu user (`sudo -u ubuntu`).

## What the test does

For each of config.SHAPES (48 shapes), sweep config.REQUEST_RATES
([0.1, 0.5, 1, 2, 5, 10, 20, 50, 100] rps) in ascending order.

1. Run `vllm bench serve` for each shape x rate:

   ```
   vllm bench serve \
     --model Qwen/Qwen3.5-4B \
     --base-url http://localhost:8000 \
     --dataset-name random \
     --random-input-len <input_tokens> \
     --random-output-len <output_tokens> \
     --random-prefix-len <prefix_tokens> \
     --request-rate <rate> \
     --num-prompts <config.num_prompts_for(rate)> \
     --save-result --result-dir /home/ubuntu/bench_results \
     --result-filename <shape_name>_rate<rate>.json
   ```

   Note: argument names vary between versions. Check
   `vllm bench serve --help` first and get one low-rate smoke test to pass
   before starting the full sweep. If `--backend` is required, try
   openai / openai-chat.

2. Saturation rule: once the measured request throughput
   (`request_throughput`) in the result JSON falls below offered rate x 0.80,
   stop that shape's sweep and move to the next shape
   (config.SATURATION_TRACKING_THRESHOLD = 0.80).

3. Runaway protection: cap the SSM timeout at 20 minutes per run. If a run
   exceeds it, abandon that shape and record why. The 50,000 input shapes are
   especially heavy.

4. Pull each result JSON off the instance (read it with `cat`) and save it under
   the local `results/` directory with the same name. A summary without the
   percentile detail is acceptable if the JSON is large.
   Required fields: shape parameters, request_rate, measured
   request_throughput, output_throughput, total_token_throughput, mean/p99
   TTFT, mean/p99 ITL(TPOT), duration, num_prompts.

5. Append progress to `results/progress.log` as you go
   (shape name, rate, measured rps, saturation verdict).

## Completion criteria and deliverables

- All 48 shapes measured up to their saturation point (or a recorded reason for
  stopping)
- `results/*.json` — measurements per shape x rate
- `results/summary.json` — saturation summary per shape
  (shape name, saturation rate, total/output tokens/sec at saturation, and the
  TTFT/ITL at that point)
- Final report: how many shapes completed, which shapes were cut short, total
  elapsed time, and anything anomalous

## Resuming

If the run stops partway and is restarted:
1. Skip any measurement JSON already present in the results directory
   (`<shape_name>_rate<rate>.json`) and continue from the first unmeasured
   shape x rate.
2. Do not delete progress.log; keep appending.
3. If a shape is partially measured, resume from its unmeasured rates. If the
   previous rate already triggered the saturation rule, treat that shape as
   complete and move on.
4. On resume, check the server health first, and if it is down, restart it with
   the documented startup command before continuing.

## Do not

- Kill the server process (`vllm serve`)
- Stop, restart, or reconfigure the instance
- Note that SSM command output is capped at roughly 24KB. Read large files in
  chunks or summarize them with jq.
