"""Closed nonsecret provider profiles; persistence is added
separately."""

import re

from labcat.credentials import ConnectionError
from labcat.models import ModelError, validate_ollama_url
from labcat.provider_catalog import API_KEY_PROVIDERS

PROVIDERS = ("none", "ollama", *API_KEY_PROVIDERS, "bedrock", "chatgpt")


DEFAULT_PROFILE = {
    "provider": "none",
    "model": "",
    "ollama_url": "http://127.0.0.1:11434",
    "aws_profile": "default",
    "aws_region": "us-west-2",
    "allow_paid_inference": False,
}


def validate_profile(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != set(DEFAULT_PROFILE):
        raise ConnectionError("Supply the complete supported connection profile.")
    if value["provider"] not in PROVIDERS:
        raise ConnectionError("Choose a supported model provider.")
    if type(value["allow_paid_inference"]) is not bool:
        raise ConnectionError("Hosted inference consent must be an explicit boolean.")
    for key, pattern in (
        ("model", r"[A-Za-z0-9_.:/-]{0,200}"),
        ("aws_profile", r"[A-Za-z0-9_.@+-]{1,128}"),
        ("aws_region", r"[a-z0-9-]{1,64}"),
    ):
        if not isinstance(value[key], str) or not re.fullmatch(pattern, value[key]):
            raise ConnectionError("A connection identifier is invalid.")
    if not isinstance(value["ollama_url"], str):
        raise ConnectionError("A local Ollama address is required.")
    try:
        local_url = validate_ollama_url(value["ollama_url"])
    except ModelError as error:
        raise ConnectionError(str(error)) from None
    if value["provider"] == "ollama" and "cloud" in value["model"].lower():
        raise ConnectionError("Choose a downloaded local Ollama model.")
    if value["provider"] in {"none", "ollama"} and value["allow_paid_inference"]:
        raise ConnectionError("Local providers do not use hosted inference consent.")
    return {**value, "ollama_url": local_url}
