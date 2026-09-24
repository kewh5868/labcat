"""Fixed, reviewed API destinations; no user-configurable hosted
endpoints.

Compatibility documentation:
https://ai.google.dev/gemini-api/docs/openai
https://api-docs.deepseek.com/
https://docs.x.ai/developers/rest-api-reference/inference/chat-completions
https://openrouter.ai/docs/api/reference/overview
"""

API_KEY_PROVIDERS = (
    "openai",
    "anthropic",
    "kimi",
    "gemini",
    "deepseek",
    "xai",
    "openrouter",
)

# host + inference path are separate because Goose OPENAI_BASE_PATH is the
# complete chat-completions path, not an SDK-style base directory.
CHAT_COMPLETION_ROUTES = {
    "kimi": ("https://api.moonshot.ai", "/v1/chat/completions"),
    "gemini": (
        "https://generativelanguage.googleapis.com",
        "/v1beta/openai/chat/completions",
    ),
    "deepseek": ("https://api.deepseek.com", "/chat/completions"),
    "xai": ("https://api.x.ai", "/v1/chat/completions"),
    "openrouter": ("https://openrouter.ai", "/api/v1/chat/completions"),
}
MODEL_LIST_ENDPOINTS = {
    "openai": "https://api.openai.com/v1/models",
    "anthropic": "https://api.anthropic.com/v1/models?limit=100",
    "kimi": "https://api.moonshot.ai/v1/models",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/models",
    "deepseek": "https://api.deepseek.com/models",
    "xai": "https://api.x.ai/v1/models",
    # Account-filtered listing respects user privacy/provider/guardrail settings.
    # Unlike the public /models catalog, this route requires authentication.
    "openrouter": "https://openrouter.ai/api/v1/models/user",
}
