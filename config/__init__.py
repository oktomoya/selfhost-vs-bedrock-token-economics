"""Configuration package for the vLLM load tests and cost calculations.

Layout:
  environment.py      test environment facts (instance / vLLM)
  pricing_bedrock.py  Bedrock pricing (per token)
  pricing_ec2.py      EC2 pricing (per hour)
  patterns.py         load test pattern definitions
  costing.py          cost calculation helpers

`import config` exposes every symbol.
"""

from .environment import INSTANCE, VLLM
from .pricing_bedrock import BEDROCK_PRICING
from .pricing_ec2 import (
    EC2_PRICING,
    EC2_INSTANCE_SP_PRICING,
    SP_PATTERNS,
    CAPACITY_BLOCK_PRICING,
    CAPACITY_BLOCK_OFFERINGS,
    ec2_hourly_usd,
    ec2_sp_hourly_usd,
    ec2_capacity_block_hourly_usd,
)
from .patterns import (
    SHAPES,
    LOAD_TEST_PATTERNS,
    REQUEST_RATES,
    SATURATION_TRACKING_THRESHOLD,
    num_prompts_for,
    TARGET_MODEL,
    RESULTS_DIR,
)
from .costing import (
    bedrock_cost_usd,
    ec2_cost_usd,
    ec2_cost_per_1m_output,
    # legacy aliases
    selfhosted_cost_usd,
    selfhosted_cost_per_1m_output,
)
