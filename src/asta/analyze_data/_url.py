"""Resolve the DataVoyager backend URL from passthrough config."""

from asta.utils.config import get_api_config


def dv_url() -> str:
    return get_api_config("analyze_data")["base_url"]
