# vLLM Load Test and Cost Comparison — Test Plan

Status: plan finalized / before execution

## 1. Purpose

Measure the token throughput of a self-hosted LLM (vLLM on EC2 P5), derive the
effective cost ($/1M tokens) per workload shape, and compare it against managed
models on Amazon Bedrock.

Compared:

| Delivery | Model / purchase option |
|---|---|
| Self-hosted | Qwen3.5-4B on p5.4xlarge (On-Demand / SP 1yr and 3yr x No/All Upfront / Capacity Blocks) |
| Bedrock | Claude Haiku 4.5 (US Geo CRIS) |
| Bedrock | GPT-5.6 Luna (US Geo CRIS) |

## 2. Test environment (verified facts)

| Item | Value |
|---|---|
| Instance | see `config/environment.py` (set via environment variables) |
| Type | p5.4xlarge — NVIDIA H100 80GB HBM3 x1 |
| OS | Ubuntu 22.04 |
| vLLM | 0.25.1 (venv: /home/ubuntu/vllm-env) |
| Model | Qwen/Qwen3.5-4B (bfloat16, max_model_len 262,144) — verified working |
| Serve config | text-only (`--language-model-only --reasoning-parser qwen3 --enable-prefix-caching`) |
| KV cache | 60.61 GiB / 1,960,086 tokens (text-only frees the vision encoder into KV) |
| Access | over SSM (no SSH) |

Known gotchas:
- When starting vLLM, put the venv bin on PATH
  (`PATH=/home/ubuntu/vllm-env/bin:$PATH`). Otherwise FlashInfer's JIT cannot
  find `ninja` and EngineCore fails to start.
- These tests run in text-only mode (the text-only setup from the official
  Qwen3.5 recipe). Prefix caching is enabled at startup, so no further
  server-side preparation is needed.

## 3. Test design

### 3.1 Method

For each "shape" (input x output x cache ratio), raise the request rate in
steps and find the point where the system can no longer keep up with the
offered rate (the saturation point). The total token throughput (tokens/sec)
just before saturation is used as the practical ceiling of one GPU for that
shape, and it feeds the cost calculation.

Measurement tool: `vllm bench serve` (bundled with vLLM), random dataset,
Poisson arrivals.

### 3.2 Shape grid (48 shapes)

| Axis | Values |
|---|---|
| Input tokens | 1,000 / 5,000 / 10,000 / 50,000 |
| Output tokens | 100 / 500 / 1,000 / 2,000 |
| Cache ratio | 10% / 50% / 80% |

Cache ratio = the share of the input that is a prefix common to every request.
Implemented as `--random-prefix-len = input x cache ratio`
(e.g. in10000 / cache80 gives a shared prefix of 8,000 plus 2,000 random).
From the second request onward, the shared part hits the prefix cache.

### 3.3 Request rate sweep

| Item | Value |
|---|---|
| Rate steps | 0.1 / 0.5 / 1 / 2 / 5 / 10 / 20 / 50 / 100 rps (ascending) |
| Arrival distribution | Poisson (`--request-rate`) |
| Saturation rule | measured req/s < offered rate x 0.80 counts as saturated; stop there |
| Duration | about 60 seconds per rate (`num_prompts = max(10, rate x 60)`) |

Expectation: across this shape range, many shapes saturate at a few rps or
below. Only light shapes with a high cache ratio should reach the high rates
(50/100 rps).

### 3.4 Metrics

- TTFT (time to first token)
- ITL / TPOT (inter-token latency)
- End-to-end latency
- Input and output token throughput (tokens/sec)
- Measured request rate (req/s)

Results are written as JSON under `results/`.

## 4. Cost calculation

Derive $/1M tokens per shape from the measured throughput and compare.

### 4.1 Self-hosted (p5.4xlarge, us-west-2)

Hourly rate x (time needed to process 1M tokens). Hourly rates by purchase
option, pulled from the AWS APIs:

| Purchase option | USD/hour | vs On-Demand |
|---|---|---|
| On-Demand | 6.88 | — |
| Capacity Blocks for ML | 5.191 | -25% |
| EC2 Instance SP 1-year No Upfront | 4.3344 | -37% |
| EC2 Instance SP 1-year All Upfront | 4.04544 | -41% |
| EC2 Instance SP 3-year No Upfront | 2.97216 | -57% |
| EC2 Instance SP 3-year All Upfront | 2.58688 | -62% |

Note: Capacity Blocks are market priced. The figure above is the published rate
($5.191 per accelerator hour); re-query the offerings API when reserving.

### 4.2 Bedrock (US Geo CRIS, USD / 1M tokens)

| Model | Input | Output | Cache read | Cache write |
|---|---|---|---|---|
| Claude Haiku 4.5 | 1.00 | 5.00 | 0.10 | 1.25 (5m) |
| GPT-5.6 Luna | 0.22 | 1.32 | 0.022 | 0.275 (30m) |

Per-shape cost on the Bedrock side is computed as "shared prefix at the
cache-read rate, remainder at the normal input rate" according to the cache
ratio, so both sides are compared on the same terms.

## 5. Execution steps

1. Restart the vLLM server with the load test configuration (text-only +
   prefix caching)
2. `run_bench.py` runs `vllm bench serve` over shapes x rates via SSM and
   collects JSON into `results/`
3. The report generator builds the comparison tables from `results/` and
   `config/`

## 6. Deliverables

- `results/*.json` — raw measurements per shape x rate
- Saturation throughput by shape
- $/1M tokens comparison by shape (6 self-hosted options vs 2 Bedrock models)

## 7. Mapping to the configuration files

The `config/` package is the source of truth for the parameters in this plan:

| File | Contents |
|---|---|
| config/environment.py | test environment facts |
| config/patterns.py | shape grid, rate sweep, saturation rule |
| config/pricing_ec2.py | EC2 pricing (OD / SP / Capacity Blocks) |
| config/pricing_bedrock.py | Bedrock pricing (Geo CRIS) |
| config/costing.py | cost calculation helpers |

If the plan and the configuration disagree, `config/` wins and this document
should be updated.
