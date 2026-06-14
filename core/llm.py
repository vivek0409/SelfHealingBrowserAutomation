import os
import httpx
from typing import Optional, Dict

# Sensible default models per provider. These can be overridden per-request
# (via the `model` argument / X-API-Model header) or globally via env vars,
# so the system supports GPT, Llama/CodeLlama, Claude, etc. without code edits.
DEFAULT_MODELS = {
    "openai": "gpt-4o",
    # Stronger default for OpenRouter: agentic discovery and code generation need
    # reliable structured-JSON output. Override per-request via the X-API-Model
    # header / Model field (e.g. "anthropic/claude-3.5-sonnet").
    "openrouter": "openai/gpt-4o",
}

# Canonical base URLs per provider.
DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


def resolve_model(provider: str, model: Optional[str]) -> str:
    """Pick the model to use: explicit arg > env override > provider default."""
    if model and model.strip():
        return model.strip()
    env_model = os.getenv("LLM_MODEL")
    if env_model:
        return env_model
    return DEFAULT_MODELS.get(provider, DEFAULT_MODELS["openai"])


def resolve_base_url(provider: str, base_url: Optional[str]) -> str:
    """
    Pick the base URL to call.

    Always anchor to the provider's canonical endpoint so an OpenRouter key is
    never sent to OpenAI (a frequent cause of 401s): for OpenRouter we ignore a
    blank URL or a stale OpenAI URL and use the OpenRouter endpoint. A genuinely
    custom URL (e.g. a local Ollama/vLLM server) is still honored.
    """
    cleaned = (base_url or "").strip()
    if provider == "openrouter":
        if not cleaned or "api.openai.com" in cleaned:
            return DEFAULT_BASE_URLS["openrouter"]
        return cleaned
    if not cleaned:
        return DEFAULT_BASE_URLS.get(provider, DEFAULT_BASE_URLS["openai"])
    return cleaned


def call_llm(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    provider: str = "openai",
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    response_format: Optional[Dict] = None
) -> str:
    """
    Calls the LLM using the provided api_key and provider details.

    Compatible with any OpenAI-style /chat/completions endpoint (OpenAI,
    OpenRouter, local servers such as Ollama/vLLM exposing the OpenAI API).
    """
    # Trim the key: copy/pasted keys frequently carry a trailing newline or
    # surrounding spaces, which the provider rejects with a 401.
    api_key = (api_key or "").strip()
    if not api_key:
        raise ValueError("API Key is required to call the LLM agent.")

    # Auto-correct the provider from the key when it is unambiguous. OpenRouter
    # keys are prefixed with "sk-or-", so a key like that must go to OpenRouter
    # even if the UI dropdown was left on the default ("openai"). This prevents a
    # 401 from sending an OpenRouter key to the OpenAI endpoint.
    if api_key.startswith("sk-or-") and provider != "openrouter":
        provider = "openrouter"
        # Drop a stale OpenAI base URL so it re-resolves to OpenRouter below.
        if base_url and "api.openai.com" in base_url:
            base_url = None

    # Determine base URL (anchored to the provider so the key/endpoint match).
    base_url = resolve_base_url(provider, base_url)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # OpenRouter requires additional headers
    if provider == "openrouter":
        headers["HTTP-Referer"] = "http://localhost:8000"
        headers["X-Title"] = "Browser Automation AI Agent"

    selected_model = resolve_model(provider, model)

    url = f"{base_url.rstrip('/')}/chat/completions"

    data = {
        "model": selected_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.1
    }

    if response_format:
        data["response_format"] = response_format

    response = None
    try:
        response = httpx.post(url, headers=headers, json=data, timeout=120.0)
        response.raise_for_status()
        res_json = response.json()
        return res_json["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        body = e.response.text
        print(f"Error calling LLM (provider={provider}, model={selected_model}, url={url}): {status} {body}")
        if status == 401:
            raise RuntimeError(
                f"Authentication failed (401) against {url}. Check that the API key is "
                f"valid for provider '{provider}' and that the provider/base URL match the "
                f"key (an OpenAI key won't work on OpenRouter and vice-versa)."
            ) from e
        raise RuntimeError(f"LLM request failed ({status}) at {url}: {body}") from e
    except Exception as e:
        print(f"Error calling LLM (provider={provider}, model={selected_model}, url={url}): {str(e)}")
        raise e
