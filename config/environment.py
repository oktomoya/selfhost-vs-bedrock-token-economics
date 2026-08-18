"""Test environment facts (instance / vLLM), verified over SSM.

Instance identifiers and AWS profile names are intentionally left as
placeholders. Set them via environment variables or edit them locally; the
report generator does not need them.
"""

import os

INSTANCE = {
    # e.g. "i-0123456789abcdef0"
    "instance_id": os.environ.get("BENCH_INSTANCE_ID", ""),
    "name": os.environ.get("BENCH_INSTANCE_NAME", "vllm-loadtest"),
    "instance_type": "p5.4xlarge",
    "region": os.environ.get("BENCH_REGION", ""),
    "az": "",
    "gpu": "NVIDIA H100 80GB HBM3 x1",
    # Hourly rates live in pricing_ec2.py
    "aws_profile": os.environ.get("AWS_PROFILE", ""),
}

VLLM = {
    "version": "0.25.1",
    "venv_bin": "/home/ubuntu/vllm-env/bin",  # must be on PATH (ninja lookup)
    "endpoint": "http://localhost:8000",       # as seen from on the instance
    "log_file": "/home/ubuntu/vllm_serve_4b_textonly.log",
    # Serve configuration used for the load tests.
    # Source: official Qwen3.5 recipe (docs.vllm.ai/projects/recipes), text-only setup
    "serve_args": [
        "--language-model-only",     # text-only: do not load the vision encoder
        "--reasoning-parser", "qwen3",
        "--enable-prefix-caching",
    ],
    "models": {
        # Verified working: health 200, chat completion OK
        "qwen3.5-4b": {
            "hf_id": "Qwen/Qwen3.5-4B",
            "cached": True,          # cached in HF cache (8.8GB)
            "verified": True,
            "max_model_len": 262_144,
            "dtype": "bfloat16",
        },
        # Cached but not exercised
        "qwen3.5-9b": {
            "hf_id": "Qwen/Qwen3.5-9B",
            "cached": True,          # 19GB
            "verified": False,
            "max_model_len": None,   # not checked
            "dtype": "bfloat16",
        },
    },
    # Effective values observed in the text-only startup log
    "defaults": {
        "gpu_memory_utilization": 0.92,
        "max_num_batched_tokens": 8192,   # chunked prefill
        "enable_prefix_caching": True,    # enabled via --enable-prefix-caching
        "kv_cache_gib": 60.61,            # text-only frees the vision encoder: 1,960,086 tokens
    },
}
