"""Generate an HTML report from load-test results.

Usage:
    python3 generate_report.py            # auto-detect results*/ -> report.html
    python3 generate_report.py out.html   # specify output filename

Can be run while tests are still in progress (renders whatever measurement JSON
exists). Re-running overwrites with the latest data. Just open report.html.

Report contents (per-instance sections):
  1. Throughput vs offered rate curves per shape (line = cache ratio, x = saturation)
  2. Saturation throughput by shape (bar chart)
  3. Table of all measurements
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

FNAME_RE = re.compile(
    r"in(?P<inp>\d+)_out(?P<out>\d+)_cache(?P<cache>\d+)_rate(?P<rate>[\d.]+)\.json"
)

SATURATION_THRESHOLD = 0.80

# results directory -> display name
SOURCES = {
    "results": "P5 (p5.4xlarge / H100 80GB)",
    "results_g7e": "g7e (g7e.2xlarge / RTX PRO 6000 96GB)",
    "results_g7": "g7 (g7.2xlarge / RTX PRO 4500 32GB)",
}


def load_results(results_dir: Path):
    """(inp, out, cache) -> records sorted by ascending rate."""
    data = defaultdict(list)
    for f in sorted(results_dir.glob("in*_rate*.json")):
        m = FNAME_RE.match(f.name)
        if not m:
            continue
        try:
            d = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue  # skip files still being written
        data[(int(m["inp"]), int(m["out"]), int(m["cache"]))].append({
            "rate": float(m["rate"]),
            "req_tps": d.get("request_throughput"),
            "total_tps": d.get("total_token_throughput"),
            "output_tps": d.get("output_throughput"),
            "mean_ttft_ms": d.get("mean_ttft_ms"),
            "p99_ttft_ms": d.get("p99_ttft_ms"),
            "mean_tpot_ms": d.get("mean_tpot_ms"),
        })
    for key in data:
        data[key].sort(key=lambda r: r["rate"])
    return dict(data)


def saturation_point(records):
    """Saturated record (None if absent) and the best observed total_tps record."""
    sat = next((r for r in records
                if r["req_tps"] < r["rate"] * SATURATION_THRESHOLD), None)
    best = max(records, key=lambda r: r["total_tps"])
    return sat, best


def build_payload():
    """Assemble the rendering data for all sources."""
    payload = []
    for dirname, label in SOURCES.items():
        d = Path(dirname)
        if not d.is_dir():
            continue
        data = load_results(d)
        if not data:
            continue
        shapes = []
        for (inp, out, cache), recs in sorted(data.items()):
            sat, best = saturation_point(recs)
            # Pre-saturation operating point: the record before saturation
            # (the last rate that was served stably)
            if sat is None:
                presat, presat_kind = recs[-1], "unsaturated"  # never saturated: best observed
            else:
                idx = recs.index(sat)
                if idx == 0:
                    presat, presat_kind = sat, "sat_at_min"    # saturated at the lowest rate
                else:
                    presat, presat_kind = recs[idx - 1], "ok"
            shapes.append({
                "inp": inp, "out": out, "cache": cache,
                "records": recs,
                "saturated": sat is not None,
                "sat_tps": (sat or best)["total_tps"],
                "sat_rate": (sat or best)["rate"],
                "presat": {
                    "kind": presat_kind,
                    "rate": presat["rate"],
                    "total_tps": presat["total_tps"],
                    "output_tps": presat["output_tps"],
                    "mean_ttft_ms": presat["mean_ttft_ms"],
                },
            })
        payload.append({
            "source": dirname,
            "label": label,
            "shapes": shapes,
            "n_measurements": sum(len(v) for v in data.values()),
        })
    return payload


def build_cost_payload():
    """Unit-price data for the cost comparison (from config/)."""
    import config

    def sp(itype, term, pay):
        try:
            return config.ec2_sp_hourly_usd(itype, "us-west-2", term, pay)
        except KeyError:
            return None

    def cb(itype):
        try:
            return config.ec2_capacity_block_hourly_usd(itype, "us-west-2")
        except KeyError:
            return None

    ec2 = {}
    for source, itype in [("results", "p5.4xlarge"),
                          ("results_g7e", "g7e.2xlarge"),
                          ("results_g7", "g7.2xlarge")]:
        ec2[source] = {
            "instance_type": itype,
            "options": {
                "OD": config.ec2_hourly_usd(itype, "us-west-2"),
                "CB": cb(itype),
                "SP1NU": sp(itype, 1, "No Upfront"),
                "SP1AU": sp(itype, 1, "All Upfront"),
                "SP3NU": sp(itype, 3, "No Upfront"),
                "SP3AU": sp(itype, 3, "All Upfront"),
            },
        }
    bedrock = {
        k: {
            "label": {"claude-haiku-4.5": "Claude Haiku 4.5",
                      "gpt-5.6-luna": "GPT-5.6 Luna"}[k],
            "input": v["input_usd_per_1m"],
            "output": v["output_usd_per_1m"],
            "cache_read": v["cache_read_usd_per_1m"],
        }
        for k, v in config.BEDROCK_PRICING.items()
    }
    return {"ec2": ec2, "bedrock": bedrock}


SERIES_KEY = [
    ("results", "#D55E00", "P5", False),
    ("results_g7e", "#CC79A7", "G7e", True),
    ("results_g7", "#009E73", "G7", False),
    ("Claude Haiku 4.5", "#0072B2", "Claude Haiku 4.5", True),
    ("GPT-5.6 Luna", "#E69F00", "GPT-5.6 Luna", True),
]

INPUT_KEY = [
    (5000, "line-solid", "5K"),
    (10000, "line-dashed", "10K"),
    (50000, "line-dotted", "50K"),
]

YMAX_MAIN = [("auto", "Auto (fit lines)", False), ("5000", "$5K", False),
             ("10000", "$10K", True), ("25000", "$25K", False),
             ("50000", "$50K", False), ("100000", "$100K", False)]

YMAX_REQ = [("auto", "Auto (fit crossover)", True), ("0.01", "$0.01", False),
            ("0.05", "$0.05", False), ("0.1", "$0.10", False),
            ("0.5", "$0.50", False), ("1", "$1.00", False)]


def render_chart_controls(suffix, ymax_id, ymax_opts, primary):
    """Build one filter block. Both blocks come from here so they stay identical.

    primary=True marks the set the JS reads values from; the other set only
    mirrors it via data-sync.
    """
    sel = 'onchange="onControlChange(this)"'
    def opts(items):
        return "\n".join(
            f'      <option value="{v}"{" selected" if s else ""}>{t}</option>'
            for v, t, s in items)

    purchase = [("OD", "On-Demand", False), ("CB", "Capacity Blocks (p5 only)", False),
                ("SP1NU", "SP 1-year No Upfront", False),
                ("SP1AU", "SP 1-year All Upfront", True),
                ("SP3NU", "SP 3-year No Upfront", False),
                ("SP3AU", "SP 3-year All Upfront", False)]
    outputs = [("500", "500", False), ("1000", "1,000", True), ("2000", "2,000", False)]
    buffers = [("1", "1x (no buffer)", False), ("5", "5x", True), ("10", "10x", False)]

    ser_cls = ' class="ser-cb"' if primary else ""
    inp_cls = ' class="inp-cb"' if primary else ""
    ser_items = "\n".join(
        f'    <label class="key-item"><input type="checkbox"{ser_cls} data-sync="ser"\n'
        f'      value="{val}"{" checked" if on else ""} {sel}>'
        f'<i class="color-swatch" style="background:{color}"></i>{text}</label>'
        for val, color, text, on in SERIES_KEY)
    inp_items = "\n".join(
        f'    <label class="key-item"><input type="checkbox"{inp_cls} data-sync="inp"\n'
        f'      value="{val}" checked {sel}>'
        f'<i class="line-sample {cls}"></i>{text}</label>'
        for val, cls, text in INPUT_KEY)

    return f"""<div class="chart-controls">
  <label>EC2 purchase option:
    <select id="ec2opt{suffix}" data-sync="opt" {sel}>
{opts(purchase)}
    </select>
  </label>
  <label>Output tokens:
    <select id="costout{suffix}" data-sync="out" {sel}>
{opts(outputs)}
    </select>
  </label>
  <label>EC2 capacity buffer:
    <select id="costbuf{suffix}" data-sync="buf" {sel}>
{opts(buffers)}
    </select>
  </label>
  <label>Y axis max:
    <select id="{ymax_id}" onchange="renderCostChart()">
{opts(ymax_opts)}
    </select>
  </label>
</div>
<div class="chart-key">
  <div class="chart-key-group"><b>Compared (color):</b>
{ser_items}
  </div>
  <div class="chart-key-group"><b>Input tokens (line style):</b>
{inp_items}
  </div>
</div>"""


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>vLLM Load Test Report — Token Throughput and Cost</title>
<!-- Charts rendered with Chart.js 4.4.1 (MIT License), loaded from the jsDelivr
     CDN: https://github.com/chartjs/Chart.js -->
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  body { font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
         margin: 24px; color: #222; }
  h1 { font-size: 22px; }
  h2 { font-size: 18px; border-bottom: 2px solid #ddd; padding-bottom: 6px; margin-top: 40px; }
  h3 { font-size: 15px; margin-top: 28px; }
  .meta { color: #777; font-size: 12px; }
  .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
  .cell { border: 1px solid #e5e5e5; border-radius: 8px; padding: 10px; }
  .cell h4 { margin: 2px 0 8px; font-size: 13px; text-align: center; }
  .wide { max-width: 1100px; }
  table { border-collapse: collapse; font-size: 12px; margin-top: 8px; }
  th, td { border: 1px solid #ddd; padding: 4px 8px; text-align: right; }
  th { background: #f5f5f5; }
  td.name { text-align: left; font-family: monospace; }
  .sat-yes { color: #c0392b; font-weight: bold; }
  .note { background: #fffbe6; border: 1px solid #f0e6b0; border-radius: 6px;
          padding: 8px 12px; font-size: 12px; margin: 12px 0; }
  .chart-controls { display: flex; align-items: flex-start; gap: 20px; flex-wrap: wrap;
                    margin: 12px 0; font-size: 12px; }
  .chart-controls select[multiple] { display: block; margin-top: 3px; min-width: 130px;
                                     font-size: 12px; }
  .key-item input[type="checkbox"] { margin: 0 2px 0 0; cursor: pointer; }
  .key-item { cursor: pointer; }
  .chart-key { display: flex; gap: 18px; flex-wrap: wrap; padding: 8px 12px;
               background: #f7f8fa; border: 1px solid #e1e4e8; border-radius: 6px;
               font-size: 12px; margin-bottom: 12px; }
  .chart-key-group { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .key-item { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }
  .color-swatch { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
  .line-sample { width: 28px; height: 0; display: inline-block; border-top-width: 3px;
                 border-top-color: #333; }
  .line-solid { border-top-style: solid; }
  .line-dashed { border-top-style: dashed; }
  .line-dotted { border-top-style: dotted; border-top-width: 4px; }
  .overview { border: 1px solid #d7dce2; border-left: 4px solid #0072B2;
              border-radius: 6px; padding: 4px 20px 12px; margin: 16px 0;
              background: #fbfcfd; font-size: 13px; line-height: 1.7; }
  .overview h3 { margin: 16px 0 4px; font-size: 14px; }
  .overview ol, .overview ul { margin: 4px 0; padding-left: 22px; }
  .overview code { background: #eef1f4; padding: 1px 4px; border-radius: 3px; }
  .formula { background: #eef1f4; border-radius: 4px; padding: 8px 12px;
             font-family: ui-monospace, monospace; font-size: 12px; margin: 6px 0; }
</style>
</head>
<body>
<h1>vLLM Load Test Report — Token Throughput and Cost</h1>

<h2>Overview — What We Measured and How We Got the Break-Even Point</h2>
<div class="overview">
<p>The main chart is <b>Required Throughput vs Cost (Break-Even)</b>. For a given monthly token
demand, it shows which is cheaper: running your own GPUs on EC2, or paying Bedrock per token.
The throughput tables and curves below it are the measurements that chart is built from.</p>

<h3>1. The two cost structures</h3>
<ul>
  <li><b>Self-hosted (EC2 + vLLM)</b>: charged per hour. You pay for instances × hours whether you
      use them or not, so cost per token drops as demand grows. One instance can only handle so
      much, and past that you add another instance, so the cost goes up in <b>steps</b>.</li>
  <li><b>Bedrock (Claude Haiku 4.5 / GPT-5.6 Luna)</b>: charged per token. Cost is proportional to
      demand, so it is a <b>straight line</b>. Idle time costs nothing.</li>
</ul>
<p>So the two lines cross somewhere: Bedrock is cheaper at low demand, EC2 is cheaper at high
demand. To find where they cross, we need one measured number: <b>how many tokens per second one
EC2 instance can handle without falling behind</b>.</p>

<h3>2. Method: raise the request rate until the server falls behind</h3>
<p>Model: <code>Qwen/Qwen3.5-4B</code> (text-only, prefix caching enabled). Load tool:
<code>vllm bench serve</code>. We raise the request rate in steps (Poisson arrivals) instead of
fixing concurrency.</p>
<p>vLLM 0.25.1, served with:</p>
<div class="formula">vllm serve Qwen/Qwen3.5-4B --language-model-only --reasoning-parser qwen3 --enable-prefix-caching</div>
<p><code>--language-model-only</code> skips the vision encoder and frees its memory for KV cache.
<code>--enable-prefix-caching</code> is off by default and is required, since the cache-ratio axis
means nothing without it. On g7.2xlarge only, <code>--max-model-len 65536</code> was added because
the default 262,144 does not fit in 32GB alongside the weights. On p5.4xlarge the startup log
reports bfloat16, gpu_memory_utilization 0.92, max_num_batched_tokens 8,192, and a KV cache of
60.61 GiB (1,960,086 tokens).</p>
<p>Each measurement is one client run:</p>
<div class="formula">vllm bench serve --model Qwen/Qwen3.5-4B --dataset-name random
 --random-input-len &lt;input − prefix&gt; --random-output-len &lt;output&gt;
 --random-prefix-len &lt;input × cache ratio&gt; --request-rate &lt;rps&gt;
 --num-prompts &lt;max(10, rate × 60)&gt; --seed &lt;per-run&gt; --ignore-eos</div>
<p><code>--random-prefix-len</code> is how the cache ratio is applied: that many tokens are shared
by every request. <code>--ignore-eos</code> forces the full output length. The seed is unique per
run, because with the default seed 0 the previous run's prompts stay in the prefix cache and
inflate the effective cache ratio.</p>
<ol>
  <li>Pick a workload shape (input tokens × output tokens × cache ratio).</li>
  <li>Raise the offered rate: <code>0.1 → 0.5 → 1 → 2 → 5 → 10 → 20 → 50 → 100 req/s</code>.</li>
  <li>Record measured throughput and TTFT at each rate.</li>
  <li><b>Saturation rule</b>: when measured <code>req/s &lt; offered rate × 0.8</code>, the server
      is not keeping up (the queue is growing and latency is climbing), so we stop.</li>
</ol>

<h3>3. Why we use the rate just before saturation</h3>
<p>Throughput at saturation is a higher number, but at that point the queue backs up and TTFT gets
too long to use. So we take the throughput at <b>one rate step before saturation</b> as what one
instance can actually handle. This means the break-even numbers assume latency stays usable.</p>

<h3>4. What we measured</h3>
<ul>
  <li><b>Input tokens</b>: 5,000 / 10,000 / 50,000 (shown as line style in the charts)</li>
  <li><b>Output tokens</b>: 500 / 1,000 / 2,000 (dropdown)</li>
  <li><b>Cache ratio</b>: 10% / 50% / 80%, set as the shared-prefix fraction. This stands for how
      much of the prompt (such as a system prompt) is reused. The charts are split by this.</li>
  <li><b>Instances</b>: p5.4xlarge / g7e.2xlarge / g7.2xlarge, same test on each</li>
</ul>
<p>That is 27 shapes per instance type (3 inputs × 3 outputs × 3 cache ratios).</p>

<h3>5. How we turn throughput into cost</h3>
<div class="formula">Self-hosted per month = ceil(required TPM ÷ (stable tokens/s × 60)) × EC2 hourly rate × 730h</div>
<div class="formula">Bedrock per month = required TPM × 60 × 730h ÷ 1,000,000 × $/1M tokens</div>
<p>The EC2 hourly rate can be set to On-Demand, Savings Plans, or Capacity Blocks with the
dropdown.</p>
<p>The Bedrock $/1M is a blended rate worked out per request, then divided by total tokens:</p>
<div class="formula">$ per request = (input × cache ratio × cache-read price
 + input × (1 − cache ratio) × input price
 + output × output price) ÷ 1,000,000</div>
<div class="formula">$/1M tokens = $ per request ÷ (input + output) × 1,000,000</div>
<p>So at cache 80%, 80% of the input is billed at the cache-read price and 20% at the normal input
price. Cache reads cost a tenth of normal input for both models: Haiku 4.5 is $0.10 vs $1.00 per
1M, Luna is $0.022 vs $0.22 per 1M. That is why the Bedrock lines drop as the cache ratio goes
from 10% to 80%.</p>
<p>Cache writes (Haiku $1.25, Luna $0.275 per 1M) are left out. A prefix is written once and then
read by many requests, so the write is small next to the reads. Note this makes the Bedrock figures
the optimistic end at high cache ratios: if a prefix were rewritten on every request, the cost at
cache 80% would be roughly twice what is shown. Prices are US Geo CRIS.</p>

<h3>6. What this does not cover</h3>
<ul>
  <li>Infrastructure cost only. It does not say the models are equal in quality
      (Qwen3.5-4B vs Haiku 4.5 vs Luna).</li>
  <li>EC2 numbers assume the instance runs at the stable operating point 24/7. If your real
      utilization is lower, your cost per token is higher.</li>
  <li>Operational work, availability design, redundancy, and scaling are not included.</li>
  <li>Bedrock throughput quotas are not included.</li>
</ul>
</div>

<h2>Cost Comparison: $/1M Tokens (Total Tokens)</h2>
<p class="meta">
Self-hosted = EC2 hourly rate ÷ <b>throughput just before saturation</b>, so it reflects running
with usable latency. Bedrock = US Geo CRIS prices, with the cache-ratio share of the input billed
at the cache-read price and the rest at the input price. Cache writes are left out, as explained in
the Overview.
Total tokens = input + output, including cache hits.
</p>
<div class="note">This compares infrastructure cost, not model quality (Qwen3.5-4B vs Haiku 4.5 vs
Luna). EC2 numbers assume the instance runs at the stable operating point 24/7; lower utilization
means higher cost per token. "—" = saturated even at the lowest rate of 0.1 rps, so there is no
stable operating point on that instance type.</div>
<label>EC2 purchase option:
<select id="ec2opt" data-sync="opt" onchange="onControlChange(this)">
  <option value="OD">On-Demand</option>
  <option value="CB">Capacity Blocks (p5 only)</option>
  <option value="SP1NU">SP 1-year No Upfront</option>
  <option value="SP1AU" selected>SP 1-year All Upfront</option>
  <option value="SP3NU">SP 3-year No Upfront</option>
  <option value="SP3AU">SP 3-year All Upfront</option>
</select></label>
<div id="costtable"></div>
<h2>Required Throughput vs Cost (Break-Even)</h2>
<p class="meta">X axis = total token throughput you need to serve (tokens per minute, TPM,
sustained). Y axis = cost per month (USD, 730 hours). Bedrock is a straight line because it is
charged per token. EC2 is a step line: instances needed (demand ÷ what one instance handles,
rounded up) × hourly rate.
Input token counts 5,000 / 10,000 / 50,000 are drawn in the same chart, and the charts are
split by cache ratio 10% / 50% / 80%. Output tokens are set with the dropdown.
The EC2 capacity buffer multiplies how much capacity you provision, so 5x means you run enough
instances for 5 times the demand. It only affects EC2, since Bedrock is charged per token and
needs no provisioning.
Use the checkboxes below to pick which lines are drawn.
<b>Color = what is being compared</b>, <b>line style = input tokens</b>. The Y axis defaults to
$10,000 per month, so lines above that are cut off at the top. Pick Auto to fit whatever is drawn,
or another fixed value to compare charts on the same scale.</p>
__CONTROLS_MAIN__
<div class="cell"><h3>Cache ratio 10%</h3>
  <div style="height:440px"><canvas id="costchart_10"></canvas></div></div>
<div class="cell" style="margin-top:16px"><h3>Cache ratio 50%</h3>
  <div style="height:440px"><canvas id="costchart_50"></canvas></div></div>
<div class="cell" style="margin-top:16px"><h3>Cache ratio 80%</h3>
  <div style="height:440px"><canvas id="costchart_80"></canvas></div></div>

<h2>Required Throughput vs Cost per Request</h2>
<p class="meta">Same data and same filters as the chart above, but the Y axis is cost per request
instead of cost per month. Requests per month = TPM × 60 × 730 ÷ (input + output).
Bedrock is a flat line: per-token billing means one request costs the same whatever your volume is.
EC2 is a sawtooth: cost per request falls as you fill an instance, then jumps when the next
instance is added. Where the sawtooth drops below the flat line is where self-hosting is cheaper
per request.
At low demand EC2 cost per request is very large, because one instance is spread over few requests,
so the left edge runs off the top of the chart.</p>
__CONTROLS_REQ__
<div class="cell"><h3>Cache ratio 10%</h3>
  <div style="height:440px"><canvas id="reqchart_10"></canvas></div></div>
<div class="cell" style="margin-top:16px"><h3>Cache ratio 50%</h3>
  <div style="height:440px"><canvas id="reqchart_50"></canvas></div></div>
<div class="cell" style="margin-top:16px"><h3>Cache ratio 80%</h3>
  <div style="height:440px"><canvas id="reqchart_80"></canvas></div></div>
<h2>Token Throughput Just Before Saturation</h2>
<p class="meta">For each shape, this is the measurement at one rate step before the saturation rule
fires. It is the last rate the server kept up with and latency was still usable. Use these numbers
for capacity planning.
Cells: total tokens/s, with the rate in req/s and mean TTFT below it.</p>
__PRESAT__
__BODY__
<script>
const CACHE_COLORS = {10: "#1f77b4", 50: "#ff7f0e", 80: "#2ca02c"};
const PAYLOAD = __PAYLOAD__;
const COST = __COST__;

// --- Cost comparison ---
function bedrockCostPer1M(shape, price) {
  // Per request: the cache% share of the input is priced at the cache-read rate,
  // the remainder at the standard input rate
  const cached = shape.inp * shape.cache / 100;
  const fresh = shape.inp - cached;
  const perReq = (cached * price.cache_read + fresh * price.input
                  + shape.out * price.output) / 1e6;
  return perReq / (shape.inp + shape.out) * 1e6;
}

function ec2CostPer1M(hourly, satTps) {
  if (hourly == null || !satTps) return null;
  return hourly / (satTps * 3600 / 1e6);
}

function renderCostTable() {
  const opt = syncedValue("opt");
  // Shape list is the union across all sources
  const shapeKeys = new Map();
  for (const src of PAYLOAD)
    for (const s of src.shapes)
      shapeKeys.set(`${s.inp}|${s.out}|${s.cache}`, s);
  const srcCols = PAYLOAD.map(src => ({
    source: src.source,
    name: COST.ec2[src.source].instance_type,
    hourly: COST.ec2[src.source].options[opt],
    shapes: new Map(src.shapes.map(s => [`${s.inp}|${s.out}|${s.cache}`, s])),
  }));
  const bedrockCols = Object.values(COST.bedrock);
  const caches = [...new Set([...shapeKeys.values()].map(s => s.cache))].sort((a,b)=>a-b);

  let html = "";
  for (const cacheVal of caches) {
    const sorted = [...shapeKeys.values()]
      .filter(s => s.cache === cacheVal)
      .sort((a, b) => a.inp - b.inp || a.out - b.out);
    html += `<h3>Cache ratio ${cacheVal}%</h3>`;
    html += "<table><tr><th>Shape</th>";
    for (const c of srcCols)
      html += `<th>${c.name}<br><span style="font-weight:normal">$${c.hourly == null ? "—" : c.hourly.toFixed(2)}/h</span></th>`;
    for (const b of bedrockCols) html += `<th>${b.label}</th>`;
    html += "</tr>";

    for (const s of sorted) {
      const key = `${s.inp}|${s.out}|${s.cache}`;
      const cells = [];
      for (const c of srcCols) {
        const sh = c.shapes.get(key);
        if (!sh || sh.presat.kind === "sat_at_min") {
          cells.push({v: null, mark: ""});  // no data, or no stable operating point
          continue;
        }
        const v = ec2CostPer1M(c.hourly, sh.presat.total_tps);
        cells.push({v, mark: sh.presat.kind === "unsaturated" ? " *" : ""});
      }
      for (const b of bedrockCols)
        cells.push({v: bedrockCostPer1M(s, b), mark: ""});
      const valid = cells.filter(c => c.v != null).map(c => c.v);
      const min = Math.min(...valid);
      html += `<tr><td class="name">in ${s.inp.toLocaleString()} / out ${s.out.toLocaleString()}</td>`;
      for (const c of cells) {
        if (c.v == null) { html += "<td>—</td>"; continue; }
        const cls = (c.v === min) ? ' style="background:#e8f6e8;font-weight:bold"' : "";
        html += `<td${cls}>$${c.v.toFixed(2)}${c.mark}</td>`;
      }
      html += "</tr>";
    }
    html += "</table>";
  }
  html += "<p class='meta'>* = did not saturate up to the highest rate tested (uses the highest measured value, so the real cost may be lower). — = no stable operating point. Green = cheapest for that shape.</p>";
  document.getElementById("costtable").innerHTML = html;
}
renderCostTable();

// --- Required throughput vs cost (break-even charts, 3 panels by cache ratio) ---
const HOURS_PER_MONTH = 730;
const SERVICE_COLORS = {
  results: "#D55E00",
  results_g7e: "#CC79A7",
  results_g7: "#009E73",
  "Claude Haiku 4.5": "#0072B2",
  "GPT-5.6 Luna": "#E69F00",
};
const INPUT_LINE_STYLES = {
  5000: {dash: [], width: 2.2},
  10000: {dash: [9, 5], width: 2.6},
  50000: {dash: [2, 4], width: 3.2},
};
const costChartObjs = {};

// Round up to a readable axis bound (1, 1.5, 2, 2.5, 3, 4, 5, 7.5 x 10^n)
function niceCeil(v) {
  if (!(v > 0)) return 1000;
  const mag = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 1.5, 2, 2.5, 3, 4, 5, 7.5]) {
    if (v <= m * mag) return m * mag;
  }
  return 10 * mag;
}

// Values of the checked boxes in a filter group
function checkedValues(cls) {
  return [...document.querySelectorAll(`input.${cls}:checked`)].map(el => el.value);
}

// The synced filters exist in two blocks, so read the first one
function syncedValue(group) {
  return document.querySelector(`[data-sync="${group}"]`).value;
}

function renderCacheCostChart(canvasId, cacheVal, opt) {
  const out = Number(syncedValue("out"));
  const series = checkedValues("ser-cb");
  const inputs = checkedValues("inp-cb").map(Number).sort((a, b) => a - b);
  const maxX = 1000000;  // shared across charts: 0-1,000K TPM
  const buffer = Number(syncedValue("buf"));
  const datasets = [];

  for (const inp of inputs) {
    const key = `${inp}|${out}|${cacheVal}`;
    const shape = {inp, out, cache: cacheVal};
    const lineStyle = INPUT_LINE_STYLES[inp];
    const inputLabel = `in ${inp / 1000}K`;

    for (const src of PAYLOAD) {
      if (!series.includes(src.source)) continue;
      const sh = src.shapes.find(s => `${s.inp}|${s.out}|${s.cache}` === key);
      const hourly = COST.ec2[src.source].options[opt];
      if (!sh || sh.presat.kind === "sat_at_min" || hourly == null) continue;

      const capTpm = sh.presat.total_tps * 60;
      const pts = [];
      const steps = 300;
      for (let i = 1; i <= steps; i++) {
        const x = maxX * i / steps;
        // Provision for buffer x the demand; Bedrock is per token so it is unaffected
        pts.push({x, y: Math.ceil(x * buffer / capTpm) * hourly * HOURS_PER_MONTH});
      }
      const color = SERVICE_COLORS[src.source];
      const bufLabel = buffer === 1 ? "" : ` ×${buffer}`;
      datasets.push({
        label: `${COST.ec2[src.source].instance_type}${bufLabel} · ${inputLabel} (${Math.round(capTpm).toLocaleString()} TPM/instance)`,
        data: pts, borderColor: color, backgroundColor: color,
        showLine: true, pointRadius: 0, stepped: true,
        borderDash: lineStyle.dash, borderWidth: lineStyle.width,
      });
    }

    for (const b of Object.values(COST.bedrock)) {
      if (!series.includes(b.label)) continue;
      const per1M = bedrockCostPer1M(shape, b);
      const color = SERVICE_COLORS[b.label];
      const monthlyPerTpm = 60 * HOURS_PER_MONTH / 1e6 * per1M;
      datasets.push({
        label: `${b.label} · ${inputLabel} ($${per1M.toFixed(2)}/1M)`,
        data: [{x: 1, y: monthlyPerTpm},
               {x: maxX, y: maxX * monthlyPerTpm}],
        borderColor: color, backgroundColor: color,
        showLine: true, pointRadius: 0,
        borderDash: lineStyle.dash, borderWidth: lineStyle.width,
      });
    }
  }

  if (costChartObjs[canvasId]) costChartObjs[canvasId].destroy();
  // Y range: fit every plotted line by default, or use the value the user picked
  const yMaxSel = document.getElementById("costymax").value;
  const dataMaxY = Math.max(0, ...datasets.flatMap(d => d.data.map(p => p.y)));
  const maxY = yMaxSel === "auto" ? niceCeil(dataMaxY) : Number(yMaxSel);
  costChartObjs[canvasId] = new Chart(document.getElementById(canvasId), {
    type: "scatter",
    data: {datasets},
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        x: {title: {display: true, text: "Required throughput (tokens/min, TPM)"},
            min: 0, max: maxX},
        y: {
          title: {display: true, text: "Monthly cost (USD)"},
          min: 0, max: maxY,
          ticks: {callback: value => `$${Number(value).toLocaleString()}`},
        },
      },
      plugins: {
        legend: {display: false},
        tooltip: {callbacks: {label: ctx =>
          `${ctx.dataset.label}: ${Math.round(ctx.parsed.x).toLocaleString()} TPM → $${Math.round(ctx.parsed.y).toLocaleString()}/mo`}},
      },
    },
  });
}

// --- Required throughput vs cost per request (same filters, per-request Y axis) ---
function renderCacheReqChart(canvasId, cacheVal, opt) {
  const out = Number(syncedValue("out"));
  const series = checkedValues("ser-cb");
  const inputs = checkedValues("inp-cb").map(Number).sort((a, b) => a - b);
  const maxX = 1000000;
  const buffer = Number(syncedValue("buf"));
  const datasets = [];
  const floors = [];  // per-request costs in the region where the lines cross

  for (const inp of inputs) {
    const key = `${inp}|${out}|${cacheVal}`;
    const shape = {inp, out, cache: cacheVal};
    const lineStyle = INPUT_LINE_STYLES[inp];
    const inputLabel = `in ${inp / 1000}K`;
    const tokensPerReq = inp + out;

    for (const src of PAYLOAD) {
      if (!series.includes(src.source)) continue;
      const sh = src.shapes.find(s => `${s.inp}|${s.out}|${s.cache}` === key);
      const hourly = COST.ec2[src.source].options[opt];
      if (!sh || sh.presat.kind === "sat_at_min" || hourly == null) continue;

      const capTpm = sh.presat.total_tps * 60;
      const pts = [];
      const steps = 600;
      for (let i = 1; i <= steps; i++) {
        const x = maxX * i / steps;
        const instances = Math.ceil(x * buffer / capTpm);
        const reqPerMonth = x * 60 * HOURS_PER_MONTH / tokensPerReq;
        pts.push({x, y: instances * hourly * HOURS_PER_MONTH / reqPerMonth});
      }
      floors.push(pts[pts.length - 1].y);
      const color = SERVICE_COLORS[src.source];
      const bufLabel = buffer === 1 ? "" : ` ×${buffer}`;
      datasets.push({
        label: `${COST.ec2[src.source].instance_type}${bufLabel} · ${inputLabel}`,
        data: pts, borderColor: color, backgroundColor: color,
        showLine: true, pointRadius: 0,
        borderDash: lineStyle.dash, borderWidth: lineStyle.width,
      });
    }

    for (const b of Object.values(COST.bedrock)) {
      if (!series.includes(b.label)) continue;
      const per1M = bedrockCostPer1M(shape, b);
      const perReq = per1M * tokensPerReq / 1e6;  // flat: no volume effect
      floors.push(perReq);
      const color = SERVICE_COLORS[b.label];
      datasets.push({
        label: `${b.label} · ${inputLabel} ($${perReq.toFixed(4)}/req)`,
        data: [{x: 1, y: perReq}, {x: maxX, y: perReq}],
        borderColor: color, backgroundColor: color,
        showLine: true, pointRadius: 0,
        borderDash: lineStyle.dash, borderWidth: lineStyle.width,
      });
    }
  }

  if (costChartObjs[canvasId]) costChartObjs[canvasId].destroy();
  // Auto range targets the crossover region, not the spike at low demand
  const yMaxSel = document.getElementById("reqymax").value;
  const maxY = yMaxSel === "auto"
    ? niceCeil(Math.max(1e-4, ...floors) * 2.5)
    : Number(yMaxSel);
  costChartObjs[canvasId] = new Chart(document.getElementById(canvasId), {
    type: "scatter",
    data: {datasets},
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        x: {title: {display: true, text: "Required throughput (tokens/min, TPM)"},
            min: 0, max: maxX},
        y: {
          title: {display: true, text: "Cost per request (USD)"},
          min: 0, max: maxY,
          ticks: {callback: value => `$${Number(value).toFixed(4)}`},
        },
      },
      plugins: {
        legend: {display: false},
        tooltip: {callbacks: {label: ctx =>
          `${ctx.dataset.label}: ${Math.round(ctx.parsed.x).toLocaleString()} TPM → $${ctx.parsed.y.toFixed(5)}/req`}},
      },
    },
  });
}

function renderCostChart() {
  const opt = syncedValue("opt");
  for (const cacheVal of [10, 50, 80]) {
    renderCacheCostChart(`costchart_${cacheVal}`, cacheVal, opt);
    renderCacheReqChart(`reqchart_${cacheVal}`, cacheVal, opt);
  }
}
renderCostChart();
// The filter blocks appear twice (monthly and per-request); mirror them by data-sync group
function onControlChange(el) {
  const group = el.dataset.sync;
  if (group) {
    for (const other of document.querySelectorAll(`[data-sync="${group}"]`)) {
      if (other === el) continue;
      if (el.type === "checkbox") {
        if (other.value === el.value) other.checked = el.checked;
      } else {
        other.value = el.value;
      }
    }
  }
  renderCostTable();
  renderCostChart();
}

function throughputChart(canvasId, shapesForCell) {
  const datasets = [];
  for (const s of shapesForCell) {
    const pts = s.records.map(r => ({x: r.rate, y: r.total_tps}));
    datasets.push({
      label: `cache ${s.cache}%`,
      data: pts,
      borderColor: CACHE_COLORS[s.cache], backgroundColor: CACHE_COLORS[s.cache],
      showLine: true, tension: 0.15,
      pointRadius: pts.map((p, i) =>
        (s.saturated && i === s.records.length - 1) ? 7 : 3.5),
      pointStyle: pts.map((p, i) =>
        (s.saturated && i === s.records.length - 1) ? "crossRot" : "circle"),
      pointBorderWidth: pts.map((p, i) =>
        (s.saturated && i === s.records.length - 1) ? 3 : 1),
    });
  }
  new Chart(document.getElementById(canvasId), {
    type: "scatter",
    data: {datasets},
    options: {
      responsive: true,
      scales: {
        x: {type: "logarithmic", title: {display: true, text: "Offered rate (req/s)"}},
        y: {beginAtZero: true, title: {display: true, text: "total tokens/s"}},
      },
      plugins: {
        legend: {labels: {boxWidth: 12, font: {size: 10}}},
        tooltip: {callbacks: {label: ctx =>
          `cache: rate ${ctx.parsed.x} → ${Math.round(ctx.parsed.y).toLocaleString()} tok/s`}},
      },
    },
  });
}

function saturationChart(canvasId, shapes) {
  const labels = shapes.map(s =>
    `in${s.inp/1000}k/out${s.out}/c${s.cache}` + (s.saturated ? "" : " *"));
  new Chart(document.getElementById(canvasId), {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "total tokens/s at saturation",
        data: shapes.map(s => s.sat_tps),
        backgroundColor: shapes.map(s =>
          CACHE_COLORS[s.cache] + (s.saturated ? "" : "66")),
      }],
    },
    options: {
      indexAxis: "y", responsive: true,
      scales: {x: {title: {display: true, text: "total tokens/s"}}},
      plugins: {legend: {display: false}},
    },
  });
}

for (const src of PAYLOAD) {
  // 3x3 grid of curves (in x out)
  const inputs = [...new Set(src.shapes.map(s => s.inp))].sort((a,b)=>a-b);
  const outputs = [...new Set(src.shapes.map(s => s.out))].sort((a,b)=>a-b);
  for (const inp of inputs) {
    for (const out of outputs) {
      const cell = src.shapes.filter(s => s.inp === inp && s.out === out);
      if (cell.length) {
        throughputChart(`curve_${src.source}_${inp}_${out}`, cell);
      }
    }
  }
  saturationChart(`sat_${src.source}`, src.shapes);
}
</script>
</body>
</html>
"""


def render_presat_table(payload):
    """Cross-instance table of pre-saturation throughput (3 tables, one per cache ratio)."""
    keys = sorted({(s["inp"], s["out"], s["cache"])
                   for src in payload for s in src["shapes"]})
    by_src = [{f'{s["inp"]}|{s["out"]}|{s["cache"]}': s for s in src["shapes"]}
              for src in payload]
    caches = sorted({c for (_, _, c) in keys})
    parts = []
    for cache in caches:
        parts.append(f"<h3>Cache ratio {cache}%</h3>")
        parts.append("<table><tr><th>Shape</th>")
        for src in payload:
            short = {"results": "p5.4xlarge", "results_g7e": "g7e.2xlarge",
                     "results_g7": "g7.2xlarge"}.get(src["source"], src["source"])
            parts.append(f"<th>{short}</th>")
        parts.append("</tr>")
        for (inp, out, c) in keys:
            if c != cache:
                continue
            parts.append(f'<tr><td class="name">in {inp:,} / out {out:,}</td>')
            for smap in by_src:
                s = smap.get(f"{inp}|{out}|{c}")
                if not s:
                    parts.append("<td>—</td>")
                    continue
                p = s["presat"]
                mark = {"ok": "", "unsaturated": " *", "sat_at_min": " †"}[p["kind"]]
                parts.append(
                    f'<td><b>{p["total_tps"]:,.0f}</b>{mark}<br>'
                    f'<span style="color:#888;font-size:11px">'
                    f'@{p["rate"]} rps, TTFT {p["mean_ttft_ms"]:,.0f}ms</span></td>')
            parts.append("</tr>")
        parts.append("</table>")
    parts.append('<p class="meta">* = did not saturate up to the highest rate tested '
                 '(highest measured value shown). '
                 '† = already saturated at the lowest rate of 0.1 rps (that value is shown; '
                 'the stable point is below 0.1 rps, so this shape is too heavy for this '
                 'instance type).</p>')
    return "\n".join(parts)


def render_body(payload):
    parts = []
    for src in payload:
        sid = src["source"]
        parts.append(f'<h2>{src["label"]}</h2>')
        parts.append(f'<p class="meta">{len(src["shapes"])} shapes / '
                     f'{src["n_measurements"]} measurements</p>')
        parts.append("<h3>Throughput vs offered rate</h3>")
        parts.append('<p class="meta">× marks the saturation point.</p>')
        inputs = sorted({s["inp"] for s in src["shapes"]})
        outputs = sorted({s["out"] for s in src["shapes"]})
        parts.append('<div class="grid">')
        for inp in inputs:
            for out in outputs:
                cell = [s for s in src["shapes"]
                        if s["inp"] == inp and s["out"] == out]
                if not cell:
                    continue
                parts.append(
                    f'<div class="cell"><h4>in {inp:,} / out {out:,}</h4>'
                    f'<canvas id="curve_{sid}_{inp}_{out}"></canvas></div>')
        parts.append("</div>")
        parts.append("<h3>Saturation throughput by shape</h3>")
        parts.append('<p class="meta">* = did not saturate up to the highest rate tested '
                     '(highest measured value shown, drawn in a lighter shade).</p>')
        h = max(160, 28 * len(src["shapes"]) + 60)
        parts.append(f'<div class="wide" style="height:{h}px">'
                     f'<canvas id="sat_{sid}"></canvas></div>')
        parts.append("<h3>All measurements</h3>")
        parts.append("<table><tr><th>Shape</th><th>rate</th><th>measured req/s</th>"
                     "<th>total tok/s</th><th>out tok/s</th>"
                     "<th>TTFT mean/p99 (ms)</th><th>TPOT mean (ms)</th>"
                     "<th>Saturated</th></tr>")
        for s in src["shapes"]:
            for r in s["records"]:
                is_sat = (s["saturated"] and r is s["records"][-1])
                parts.append(
                    f'<tr><td class="name">in{s["inp"]}_out{s["out"]}'
                    f'_cache{s["cache"]}</td>'
                    f'<td>{r["rate"]}</td><td>{r["req_tps"]:.2f}</td>'
                    f'<td>{r["total_tps"]:,.0f}</td>'
                    f'<td>{r["output_tps"]:,.0f}</td>'
                    f'<td>{r["mean_ttft_ms"]:,.0f} / {r["p99_ttft_ms"]:,.0f}</td>'
                    f'<td>{r["mean_tpot_ms"]:.1f}</td>'
                    f'<td class="{"sat-yes" if is_sat else ""}">'
                    f'{"YES" if is_sat else ""}</td></tr>')
        parts.append("</table>")
    return "\n".join(parts)


def main():
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("report.html")
    payload = build_payload()
    if not payload:
        print("No measurement JSON found")
        sys.exit(1)
    html = (HTML_TEMPLATE
            .replace("__CONTROLS_MAIN__",
                     render_chart_controls("_chart", "costymax", YMAX_MAIN, True))
            .replace("__CONTROLS_REQ__",
                     render_chart_controls("_req", "reqymax", YMAX_REQ, False))
            .replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))
            .replace("__COST__", json.dumps(build_cost_payload(), ensure_ascii=False))
            .replace("__PRESAT__", render_presat_table(payload))
            .replace("__BODY__", render_body(payload)))
    out_path.write_text(html)
    for src in payload:
        print(f"{src['source']}: {len(src['shapes'])} shapes "
              f"/ {src['n_measurements']} measurements")
    print(f"Generated: {out_path}")


if __name__ == "__main__":
    main()
