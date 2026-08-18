"""EC2 pricing (USD) by purchase option: On-Demand / EC2 Instance Savings Plans / Capacity Blocks for ML.

All figures were pulled from AWS APIs:
  - On-Demand:         AWS Pricing API (get-products)
  - Savings Plans:     savingsplans describe-savings-plans-offering-rates
  - Capacity Blocks:   ec2 describe-capacity-block-offerings (market priced, so it moves)

Key facts:
  - Capacity Blocks for ML only supports p5.48xlarge (a full H100x8 node).
    p5.4xlarge is not eligible (confirmed by API error).
  - Savings Plans rates are the effective hourly rate for a commitment (1yr/3yr).
"""

# =============================================================================
# On-Demand (USD / hour)
# =============================================================================

EC2_PRICING = {
    ("p5.4xlarge", "ap-northeast-1"): {
        "on_demand_usd_per_hour": 8.60,
        "gpu": "NVIDIA H100 80GB HBM3 x1",
        "notes": "Instance type used for the tests (Tokyo)",
    },
    ("p5.4xlarge", "us-west-2"): {
        "on_demand_usd_per_hour": 6.88,
        "gpu": "NVIDIA H100 80GB HBM3 x1",
        "notes": "Oregon. Reference region for comparison with Bedrock US Geo CRIS. 20% below Tokyo",
    },
    ("p5.48xlarge", "ap-northeast-1"): {
        "on_demand_usd_per_hour": 68.80,
        "gpu": "NVIDIA H100 80GB HBM3 x8",
        "notes": "Full node (Tokyo)",
    },
    ("p5.48xlarge", "us-west-2"): {
        "on_demand_usd_per_hour": 55.04,
        "gpu": "NVIDIA H100 80GB HBM3 x8",
        "notes": "Full node (Oregon). Only this size supports Capacity Blocks",
    },
    # --- g7 / g7e (Blackwell generation, single-GPU sizes; from the Pricing API) ---
    ("g7.2xlarge", "us-west-2"): {
        "on_demand_usd_per_hour": 2.52,
        "gpu": "NVIDIA RTX PRO 4500 32GB x1",
        "notes": "vCPU 8 / RAM 32GB",
    },
    ("g7.4xlarge", "us-west-2"): {
        "on_demand_usd_per_hour": 3.04208,
        "gpu": "NVIDIA RTX PRO 4500 32GB x1",
        "notes": "vCPU 16 / RAM 64GB. Matches p5.4xlarge on vCPU count",
    },
    ("g7.8xlarge", "us-west-2"): {
        "on_demand_usd_per_hour": 4.08624,
        "gpu": "NVIDIA RTX PRO 4500 32GB x1",
        "notes": "vCPU 32 / RAM 128GB",
    },
    ("g7e.2xlarge", "us-west-2"): {
        "on_demand_usd_per_hour": 3.36312,
        "gpu": "NVIDIA RTX PRO 6000 Server 96GB x1",
        "notes": "vCPU 8 / RAM 64GB",
    },
    ("g7e.4xlarge", "us-west-2"): {
        "on_demand_usd_per_hour": 3.99816,
        "gpu": "NVIDIA RTX PRO 6000 Server 96GB x1",
        "notes": "vCPU 16 / RAM 128GB. Matches p5.4xlarge on vCPU count",
    },
    ("g7e.8xlarge", "us-west-2"): {
        "on_demand_usd_per_hour": 5.26824,
        "gpu": "NVIDIA RTX PRO 6000 Server 96GB x1",
        "notes": "vCPU 32 / RAM 256GB",
    },
}

# =============================================================================
# EC2 Instance Savings Plans (effective USD / hour)
#   Key: (instance_type, region) -> {(term_years, payment_option): rate}
#   The rate is the effective hourly rate after the SP is applied. All Upfront
#   is the prepaid amount spread over the term.
#   Patterns used here: 1yr/3yr x No Upfront/All Upfront (four combinations)
# =============================================================================

EC2_INSTANCE_SP_PRICING = {
    ("p5.4xlarge", "us-west-2"): {
        (1, "No Upfront"):  4.3344,   # 37% below On-Demand
        (1, "All Upfront"): 4.04544,  # 41% below On-Demand
        (3, "No Upfront"):  2.97216,  # 57% below On-Demand
        (3, "All Upfront"): 2.58688,  # 62% below On-Demand
    },
    # g7 / g7e pulled from the API. Capacity Blocks are deliberately not used here
    ("g7.4xlarge", "us-west-2"): {
        (1, "No Upfront"):  2.1903,   # 28% below On-Demand
        (1, "All Upfront"): 1.78874,  # 41% below On-Demand
        (3, "No Upfront"):  1.4602,   # 52% below On-Demand
        (3, "All Upfront"): 1.14382,  # 62% below On-Demand
    },
    ("g7e.4xlarge", "us-west-2"): {
        (1, "No Upfront"):  2.51884,  # 37% below On-Demand
        (1, "All Upfront"): 2.35092,  # 41% below On-Demand
        (3, "No Upfront"):  1.72721,  # 57% below On-Demand
        (3, "All Upfront"): 1.50331,  # 62% below On-Demand
    },
    # 2xlarge: the size actually used for the load tests
    ("g7.2xlarge", "us-west-2"): {
        (1, "No Upfront"):  1.8144,
        (1, "All Upfront"): 1.48176,
        (3, "No Upfront"):  1.2096,
        (3, "All Upfront"): 0.94752,
    },
    ("g7e.2xlarge", "us-west-2"): {
        (1, "No Upfront"):  2.11877,
        (1, "All Upfront"): 1.97751,
        (3, "No Upfront"):  1.45287,
        (3, "All Upfront"): 1.26453,
    },
}

# The SP patterns used in the calculations (term_years, payment_option)
SP_PATTERNS = [
    (1, "No Upfront"),
    (1, "All Upfront"),
    (3, "No Upfront"),
    (3, "All Upfront"),
]

# =============================================================================
# Capacity Blocks for ML (paid upfront, USD)
#   Published prices: aws.amazon.com/ec2/capacityblocks/pricing/
#     p5 (us-west-2): $5.191 per accelerator hour
#       - p5.4xlarge  (H100x1): $5.191 per instance hour
#       - p5.48xlarge (H100x8): $41.528 per instance hour
#   This matches the real API offering ($996.67/24h = $41.53/h for p5.48xlarge).
#   Notes:
#     - p5.4xlarge is an eligible type, but at the time of the query there were
#       no available offerings in us-west-2 (neither 24h nor 48h). Re-run
#       describe-capacity-block-offerings for availability and real prices
#       before reserving.
#     - OS charges are separate (Amazon Linux is free; RHEL and others add an
#       OS rate).
# =============================================================================

CAPACITY_BLOCK_PRICING = {
    ("p5.4xlarge", "us-west-2"): {
        "usd_per_accelerator_hour": 5.191,   # from the published pricing page
        "usd_per_instance_hour": 5.191,      # same value, since it is H100 x1
        "accelerators": 1,
        "notes": "No offerings available at query time; price is from the published page",
    },
    ("p5.48xlarge", "us-west-2"): {
        "usd_per_accelerator_hour": 5.191,
        "usd_per_instance_hour": 41.528,     # 5.191 x 8 GPUs
        "accelerators": 8,
    },
}

# Real offerings at query time (describe-capacity-block-offerings)
CAPACITY_BLOCK_OFFERINGS = {
    ("p5.48xlarge", "us-west-2"): [
        {"duration_hours": 24, "upfront_fee_usd": 996.67,  "usd_per_hour": 41.53},
        {"duration_hours": 22, "upfront_fee_usd": 917.08,  "usd_per_hour": 41.69},
        {"duration_hours": 46, "upfront_fee_usd": 1913.75, "usd_per_hour": 41.60},
    ],
}


# =============================================================================
# Lookup functions
# =============================================================================

def ec2_hourly_usd(instance_type: str, region: str = "ap-northeast-1") -> float:
    """On-Demand hourly rate (USD). Raises KeyError if not registered."""
    return EC2_PRICING[(instance_type, region)]["on_demand_usd_per_hour"]


def ec2_sp_hourly_usd(instance_type: str, region: str,
                      term_years: int = 3,
                      payment: str = "No Upfront") -> float:
    """Effective hourly rate under EC2 Instance Savings Plans (USD)."""
    return EC2_INSTANCE_SP_PRICING[(instance_type, region)][(term_years, payment)]


def ec2_capacity_block_hourly_usd(instance_type: str, region: str = "us-west-2") -> float:
    """Published effective hourly rate for Capacity Blocks for ML (USD per instance hour).
    Market priced, so re-query describe-capacity-block-offerings when reserving."""
    return CAPACITY_BLOCK_PRICING[(instance_type, region)]["usd_per_instance_hour"]
