"""Resolve the feedback backend URL from apis config."""

from asta.utils.config import get_api_config


def feedback_url() -> str:
    return get_api_config("feedback")["base_url"]
