# Self-hosted vLLM vs Bedrock — Token Cost Benchmarks

Measured token throughput for Qwen3.5-4B served by vLLM on three EC2 GPU
instance types, converted into cost, and compared against per-token pricing for
Claude Haiku 4.5 and GPT-5.6 Luna on Amazon Bedrock.

The question it answers: **for a given monthly token demand, is it cheaper to run
your own GPUs or to pay Bedrock per token?**

Open `report.html` in a browser for the interactive report. Nothing needs to be
served; it is a single self-contained file.

## Why measurement is needed

The two options have different cost shapes:

- **Self-hosted (EC2 + vLLM)** is charged per hour. One instance handles only so
  much, and past that you add another instance, so cost rises in **steps**.
- **Bedrock** is charged per token, so cost is a **straight line** through the
  origin and idle time is free.

The two therefore cross somewhere. Locating the crossing requires one measured
number: how many tokens per second one instance sustains *without falling
behind*. That is what this repository measures.

## Method

Load is generated with `vllm bench serve` using Poisson arrivals. Rather than
fixing concurrency, the request rate is raised in steps:

```
0.1 → 0.5 → 1 → 2 → 5 → 10 → 20 → 50 → 100 req/s
```

A shape is **saturated** once measured `req/s < offered rate × 0.8`, meaning the
queue is growing and latency is diverging. The sweep stops there.

Capacity is taken from **one rate step before saturation**, not from saturation
itself. Throughput at saturation is a larger number, but TTFT there is too long
to use in production, so it would overstate what an instance can really do.

### Grid

48 shapes per instance type (4 × 4 × 3):

| Axis | Values |
|---|---|
| Input tokens | 1,000 / 5,000 / 10,000 / 50,000 |
| Output tokens | 100 / 500 / 1,000 / 2,000 |
| Cache ratio | 10% / 50% / 80% |

The 1,000-token input and 100-token output rows were added after the first
27-shape (3 × 3 × 3) run. A per-request front stage (one-shot intent
classification and tool-argument extraction) runs around 700-1,000 input tokens
and emits on the order of tens of output tokens, both below the original floors
(5,000 input / 500 output), so the first grid could only bound its throughput
from below. The in=1,000 / out=100 cells bracket that shape directly. Output is
decode-bound, so out=100 versus out=500 moves throughput a lot for light inputs.

Cache ratio is the fraction of the input that is a prefix shared by every
request, supplied via `--random-prefix-len`. It stands in for how much of a
prompt (a system prompt, for instance) gets reused and hits the prefix cache.

### Under test

| Instance | GPU | Shapes | Measurements |
|---|---|---|---|
| p5.4xlarge | NVIDIA H100 80GB x1 | 27 | 127 |
| g7e.2xlarge | NVIDIA RTX PRO 6000 Server 96GB x1 | 27 | 96 |
| g7.2xlarge | NVIDIA RTX PRO 4500 32GB x1 | 27 | 58 |

Model: `Qwen/Qwen3.5-4B`, text-only (`--language-model-only`), prefix caching
enabled. Measurement counts differ because a faster instance sustains more rate
steps before saturating.

g7.2xlarge has 32GB of GPU memory, so it was run with `--max-model-len 65536`;
the others used the default. That difference is worth keeping in mind when
reading its numbers.

## vLLM configuration

vLLM 0.25.1, installed in a venv at `/home/ubuntu/vllm-env`.

### Server

```bash
vllm serve Qwen/Qwen3.5-4B \
  --language-model-only \
  --reasoning-parser qwen3 \
  --enable-prefix-caching
```

On g7.2xlarge only, add `--max-model-len 65536`.

| Flag | Why |
|---|---|
| `--language-model-only` | text-only; skips loading the vision encoder, which frees its memory for KV cache |
| `--reasoning-parser qwen3` | per the official Qwen3.5 recipe |
| `--enable-prefix-caching` | required — the cache-ratio axis is meaningless without it, and it is off by default |
| `--max-model-len 65536` | g7 only; the default 262,144 does not fit in 32GB alongside the weights |

Effective values observed in the startup log on p5.4xlarge:

| Setting | Value |
|---|---|
| dtype | bfloat16 |
| max_model_len | 262,144 (default) |
| gpu_memory_utilization | 0.92 (default) |
| max_num_batched_tokens | 8,192 (chunked prefill) |
| KV cache | 60.61 GiB / 1,960,086 tokens |

The venv `bin` must be on `PATH` when invoking vllm
(`PATH=/home/ubuntu/vllm-env/bin:$PATH`). Without it, FlashInfer's JIT cannot
find `ninja` and EngineCore fails to start.

### Benchmark client

```bash
vllm bench serve \
  --model Qwen/Qwen3.5-4B \
  --base-url http://localhost:8000 \
  --dataset-name random \
  --random-input-len <input - prefix> \
  --random-output-len <output tokens> \
  --random-prefix-len <input × cache ratio> \
  --request-rate <rps> \
  --num-prompts <max(10, rate × 60)> \
  --seed <per-run> \
  --ignore-eos \
  --save-result --result-dir <dir> --result-filename <shape>_rate<rate>.json
```

| Flag | Why |
|---|---|
| `--dataset-name random` | synthetic prompts, so input and output lengths are exact |
| `--random-prefix-len` | implements the cache ratio as a shared prefix across requests |
| `--random-input-len` | set to `input − prefix`, because total input is the sum of the two |
| `--request-rate` | Poisson arrivals at this rate; the swept axis |
| `--num-prompts` | sized for roughly 60 seconds per rate |
| `--seed` | unique per run; with the default seed 0, prompts from the previous run stay in the prefix cache and inflate the measured cache ratio |
| `--ignore-eos` | forces the full output length so output tokens are not cut short |

Where the flags come from in code: `config/environment.py` (server) and the
`bench_cmd` in `run_bench.py` (client). `config/patterns.py` derives
`random_tokens`, `prefix_tokens` and `num_prompts_for()`.

## Cost model

```
Self-hosted per month = ceil(required TPM ÷ (stable tokens/s × 60) × buffer) × hourly rate × 730h
Bedrock per month     = required TPM × 60 × 730h ÷ 1,000,000 × blended $/1M
```

The Bedrock blended rate prices the cache-ratio share of the input at the
cache-read rate, the remainder at the input rate, and the output at the output
rate (US Geo CRIS). Cache **writes are excluded**: a prefix is written once and
read many times. This makes the Bedrock figures the optimistic end at high cache
ratios — if a prefix were rewritten on every request, cost at cache 80% would be
roughly double.

EC2 rates cover On-Demand, EC2 Instance Savings Plans (1yr/3yr × No/All Upfront)
and Capacity Blocks, all pulled from AWS APIs. The report lets you switch
between them, along with output length, a capacity buffer (1x/5x/10x), and which
series to draw.

## Example figures

Stable throughput at input 10,000 / output 1,000 / cache 50%:

| Instance | Stable total tok/s | at rate | TTFT mean |
|---|---|---|---|
| p5.4xlarge | 19,942 | 2.0 rps | 177 ms |
| g7e.2xlarge | 17,853 | 2.0 rps | 328 ms |
| g7.2xlarge | 952 | 0.1 rps | 605 ms |

Converted to cost for the same shape, at SP 1-year All Upfront:

| Option | $/1M total tokens |
|---|---|
| g7e.2xlarge | 0.031 |
| p5.4xlarge | 0.056 |
| g7.2xlarge | 0.432 |
| GPT-5.6 Luna | 0.230 |
| Claude Haiku 4.5 | 0.955 |

These are single cells from the grid and they move a lot with the shape.
Read the report rather than generalising from them.

## Repository layout

```
generate_report.py     builds report.html from results*/ and config/
report.html            the interactive report (generated)
config/
  environment.py       instance and vLLM facts (ids come from env vars)
  patterns.py          shape grid, rate sweep, saturation rule
  pricing_ec2.py       EC2 pricing: On-Demand / Savings Plans / Capacity Blocks
  pricing_bedrock.py   Bedrock pricing (US Geo CRIS)
  costing.py           cost helpers
run_bench.py           sweep driver (p5), over SSM
run_bench_g7.py        g7 variant, with spot-interruption handling
run_bench_g7e.py       g7e variant, with spot-interruption handling
results/               raw measurements, p5
results_g7/            raw measurements, g7
results_g7e/           raw measurements, g7e
TEST_PLAN.md           full test plan
RUNBOOK.md             how to run the sweep
RUNBOOK_g7.md          g7 differences
RUNBOOK_g7e.md         g7e differences
```

Each `results*/` holds one JSON per shape × rate plus a `summary.json` of
saturation points.

## Regenerating the report

```bash
python3 generate_report.py            # writes report.html
python3 generate_report.py out.html   # or a filename of your choice
```

No dependencies beyond the standard library. Chart.js is loaded from a CDN by
the generated HTML, so viewing the report needs network access.

## Reproducing the measurements

You need an EC2 GPU instance running vLLM with `Qwen/Qwen3.5-4B`, reachable over
SSM. See RUNBOOK.md for the server startup command and the required environment
variables:

```bash
export AWS_PROFILE=<profile>          # needs SSM access to the instance
export BENCH_REGION=<region>
export BENCH_INSTANCE_ID=<instance-id>
python3 run_bench.py
```

The driver is resumable: shape × rate combinations that already have a result
JSON are skipped, so it can be stopped and restarted.

## Dependencies and attribution

The Python code uses the **standard library only** — there is no
`requirements.txt` because there is nothing to install.

| Component | Version | License | How it is used |
|---|---|---|---|
| [Chart.js](https://github.com/chartjs/Chart.js) | 4.4.1 | [MIT](https://github.com/chartjs/Chart.js/blob/master/LICENSE.md) | Renders the charts in `report.html`. Loaded from the jsDelivr CDN at view time, not bundled or redistributed here. |
| [vLLM](https://github.com/vllm-project/vllm) | 0.25.1 | [Apache 2.0](https://github.com/vllm-project/vllm/blob/main/LICENSE) | Serves the model and generates load via `vllm bench serve`. Runs on the instance under test; no vLLM code is included here. |
| [Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) | — | see the model card | The model being served. Weights are downloaded from Hugging Face and are not included here. |
| AWS CLI | — | Apache 2.0 | Used by `run_bench*.py` to drive the instance over SSM. |

None of the above is vendored into this repository, so their license notices are
not reproduced here; follow the links for the authoritative terms. This
repository's own code is covered by `LICENSE`.

Because `report.html` pulls Chart.js from a CDN, viewing the report requires
network access. If you need it fully offline, download
`chart.umd.min.js` and point the `<script>` tag in `generate_report.py` at the
local copy — in that case you would be redistributing Chart.js, and its MIT
notice must travel with it.

## Limitations

- **Infrastructure cost only.** Qwen3.5-4B is not equivalent in quality to
  Haiku 4.5 or Luna. This compares what it costs to move tokens, not what those
  tokens are worth.
- Self-hosted figures assume the instance runs at its measured capacity 24/7.
  Real utilisation below that raises cost per token proportionally — the
  capacity buffer control in the report exists to make that explicit.
- Operational effort, availability design, redundancy and autoscaling are not
  priced.
- Bedrock throughput quotas are not considered.
- Prices were captured at a point in time and will drift. `config/pricing_*.py`
  holds them in one place.
- A single instance of each type was tested, so results include whatever
  variance that implies.
