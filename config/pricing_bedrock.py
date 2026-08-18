"""Bedrock pricing (USD per 1M tokens).

Sources:
  - aws.amazon.com/bedrock/pricing (checked in a browser)
  - GPT-5.6 Luna: docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-56-luna.html
GPT-5.6 Luna rates are for Geo CRIS (geographic cross-region inference, US).
"""

BEDROCK_PRICING = {
    "claude-haiku-4.5": {
        # Geo CRIS (US geography) rates. Anthropic models carry no CRIS surcharge
        # (the source-region rate applies), so this matches On-Demand.
        # Source: model card model-card-anthropic-claude-haiku-4-5.html
        "model_id": "anthropic.claude-haiku-4-5-20251001-v1:0",
        "inference_profile_id": "us.anthropic.claude-haiku-4-5-20251001-v1:0",  # Geo CRIS
        "inference_option": "Geo CRIS",
        "input_usd_per_1m": 1.00,
        "output_usd_per_1m": 5.00,
        "cache_write_usd_per_1m": 1.25,  # 5 minute TTL (1.25x the input rate)
        "cache_read_usd_per_1m": 0.10,
        "context_window": 200_000,
    },
    "gpt-5.6-luna": {
        # Geo CRIS (US geography) rates, e.g. used from Oregon us-west-2
        # Source: model card model-card-openai-gpt-56-luna.html
        # Short context window (272K) pricing. Long context (1M) differs ($0.44/$1.98)
        "model_id": "openai.gpt-5.6-luna",
        "inference_profile_id": "us.openai.gpt-5.6-luna",  # Geo CRIS
        "inference_option": "Geo CRIS",
        "input_usd_per_1m": 0.22,
        "output_usd_per_1m": 1.32,
        "cache_write_usd_per_1m": 0.275,  # 30 minute cache write
        "cache_read_usd_per_1m": 0.022,
        "context_window": 272_000,
    },
}
