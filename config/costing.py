"""Cost calculation helpers."""

from __future__ import annotations

from .environment import INSTANCE
from .pricing_bedrock import BEDROCK_PRICING
from .pricing_ec2 import ec2_hourly_usd


def bedrock_cost_usd(model_key: str, input_tokens: int, output_tokens: int) -> float:
    """Per-token cost on Bedrock (USD)."""
    p = BEDROCK_PRICING[model_key]
    return (input_tokens / 1e6) * p["input_usd_per_1m"] \
         + (output_tokens / 1e6) * p["output_usd_per_1m"]


def ec2_cost_usd(elapsed_seconds: float,
                 instance_type: str | None = None,
                 region: str | None = None) -> float:
    """EC2 running-time cost (USD). Defaults to the instance under test."""
    itype = instance_type or INSTANCE["instance_type"]
    reg = region or INSTANCE["region"]
    return ec2_hourly_usd(itype, reg) * elapsed_seconds / 3600.0


def ec2_cost_per_1m_output(output_tokens_per_sec: float,
                           instance_type: str | None = None,
                           region: str | None = None) -> float:
    """Cost per 1M output tokens (USD), derived from measured throughput.
    A theoretical figure that assumes the GPU is fully utilized."""
    seconds_per_1m = 1e6 / output_tokens_per_sec
    return ec2_cost_usd(seconds_per_1m, instance_type, region)


# Legacy compatibility aliases
selfhosted_cost_usd = ec2_cost_usd
selfhosted_cost_per_1m_output = ec2_cost_per_1m_output
