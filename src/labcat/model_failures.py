"""Closed provider failure categories; never expose remote response
contents."""

from labcat.models import ModelError

PROVIDER_FAILURE_MESSAGES = {
    "provider_usage_limit": (
        "The connected model account has exhausted its available credits or usage "
        "allowance. Changing your question will not resolve this. Check usage and "
        "billing with your provider, wait for the allowance to reset, or choose "
        "another account or model in Connections. "
        "Labcat did not automatically resubmit your question."
    ),
    "provider_rate_limit": (
        "The model provider is temporarily rate-limiting requests. Your question "
        "does not need more detail. Wait before trying again, or choose another "
        "account or model in Connections. "
        "Labcat did not automatically resubmit your question."
    ),
    "provider_authentication": (
        "The model provider could not authenticate this account. Reconnect it or "
        "choose another account in Connections. Your question does not need more "
        "detail. Labcat did not automatically resubmit your question."
    ),
}


def provider_failure_code(error):
    """Accept only known transport categories, never infer from error
    prose."""
    code = getattr(error, "failure_code", None)
    return code if type(code) is str and code in PROVIDER_FAILURE_MESSAGES else None


def research_model_error(error):
    """Preserve a known category while discarding all original error
    contents."""
    code = provider_failure_code(error)
    safe = ModelError(
        PROVIDER_FAILURE_MESSAGES[code]
        if code
        else "The language-model request failed. No report was saved. Labcat did not "
        "automatically resubmit your question. Check the connection and quota."
    )
    if code:
        safe.failure_code = code
    return safe
