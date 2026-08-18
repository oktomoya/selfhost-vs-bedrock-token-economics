"""Load test pattern definitions (for `vllm bench serve`).

Method:
  For each "shape" (input x output x cache ratio), raise the request rate (rps)
  in steps from 0.1 to 100 and find the point where the system can no longer
  keep up with the offered rate (the saturation point). The total throughput
  (tokens/sec) just before saturation is the practical ceiling of one GPU for
  that shape, and it is the input to the cost calculation.

Three-axis shape grid:
  - Input tokens:   5,000 / 10,000 / 50,000
  - Output tokens:  500 / 1,000 / 2,000
  - Cache ratio:    10% / 50% / 80%
    (the share of the input that is a prefix common to every request,
     implemented with --random-prefix-len of vllm bench serve:
     prefix = input * ratio, random part = input - prefix)

Grid = 3 x 3 x 3 = 27 shapes.

Request rate sweep:
  Run REQUEST_RATES in ascending order (Poisson arrivals). At each rate, if
    measured throughput (req/s) < offered rate x SATURATION_TRACKING_THRESHOLD
  treat it as saturated and skip the remaining higher rates.
  Record the token throughput at the saturation point.

Assumptions:
  - The server must be started with --enable-prefix-caching
    (off by default; see defaults in environment.py)
  - Metrics collected: TTFT / ITL(TPOT) / E2E / input and output tokens/sec /
    measured req/s

Matching vllm bench serve arguments:
  --dataset-name random
  --random-input-len <input_tokens>
  --random-output-len <output_tokens>
  --random-prefix-len <prefix_tokens>
  --request-rate <rps>          (Poisson arrivals; inf sends everything at once)
  --num-prompts <num_prompts>
"""

INPUT_TOKENS = [5_000, 10_000, 50_000]
OUTPUT_TOKENS = [500, 1_000, 2_000]
CACHE_RATIOS = [0.10, 0.50, 0.80]

# Request rate sweep (rps, run ascending and cut off once saturated)
REQUEST_RATES = [0.1, 0.5, 1, 2, 5, 10, 20, 50, 100]

# Saturation rule: treat as saturated once measured req/s falls below this
# fraction of the offered rate
SATURATION_TRACKING_THRESHOLD = 0.80

# Target measurement duration per rate (seconds) and a floor on request count
TARGET_DURATION_SEC = 60
MIN_NUM_PROMPTS = 10


def num_prompts_for(rate_rps: float) -> int:
    """Request count for a rate (enough for the target duration, at least MIN_NUM_PROMPTS)."""
    return max(MIN_NUM_PROMPTS, int(rate_rps * TARGET_DURATION_SEC))


def build_shapes():
    """Generate all 27 shapes from the three-axis grid."""
    shapes = []
    for input_tokens in INPUT_TOKENS:
        for output_tokens in OUTPUT_TOKENS:
            for cache_ratio in CACHE_RATIOS:
                prefix = int(input_tokens * cache_ratio)
                shapes.append({
                    "name": f"in{input_tokens}_out{output_tokens}_cache{int(cache_ratio*100)}",
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_ratio": cache_ratio,
                    "prefix_tokens": prefix,          # --random-prefix-len
                    "random_tokens": input_tokens - prefix,
                })
    return shapes


SHAPES = build_shapes()

# Legacy alias
LOAD_TEST_PATTERNS = SHAPES

# Model under test (default)
TARGET_MODEL = "qwen3.5-4b"

# Where results are written
RESULTS_DIR = "results"
