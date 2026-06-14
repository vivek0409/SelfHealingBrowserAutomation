import os
from typing import Optional, Dict
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

DEFAULT_MODELS = {
    "openai": "gpt-4o",
    "openrouter": "openai/gpt-4o",
}

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


def resolve_model(provider: str, model: Optional[str]) -> str:
    if model and model.strip():
        return model.strip()
    env_model = os.getenv("LLM_MODEL")
    if env_model:
        return env_model
    return DEFAULT_MODELS.get(provider, DEFAULT_MODELS["openai"])


def resolve_base_url(provider: str, base_url: Optional[str]) -> str:
    cleaned = (base_url or "").strip()
    if provider == "openrouter":
        if not cleaned or "api.openai.com" in cleaned:
            return DEFAULT_BASE_URLS["openrouter"]
        return cleaned
    if not cleaned:
        return DEFAULT_BASE_URLS.get(provider, DEFAULT_BASE_URLS["openai"])
    return cleaned


def _normalize(api_key: str, provider: str, base_url: Optional[str]):
    """Auto-correct provider when the key prefix makes it unambiguous."""
    api_key = (api_key or "").strip()
    if api_key.startswith("sk-or-") and provider != "openrouter":
        provider = "openrouter"
        if base_url and "api.openai.com" in base_url:
            base_url = None
    return api_key, provider, base_url


def get_llm(
    api_key: str,
    provider: str = "openai",
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> ChatOpenAI:
    """Return a LangChain ChatOpenAI instance configured for the given provider."""
    api_key, provider, base_url = _normalize(api_key, provider, base_url)
    if not api_key:
        raise ValueError("API Key is required to call the LLM.")

    extra_headers: Dict[str, str] = {}
    if provider == "openrouter":
        extra_headers = {
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Browser Automation AI Agent",
        }

    return ChatOpenAI(
        model=resolve_model(provider, model),
        openai_api_key=api_key,
        openai_api_base=resolve_base_url(provider, base_url),
        temperature=0.1,
        request_timeout=120,
        **({"default_headers": extra_headers} if extra_headers else {}),
    )


def call_llm(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    provider: str = "openai",
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    response_format: Optional[Dict] = None,
) -> str:
    """
    LangChain-backed drop-in replacement for the original httpx-based caller.
    Accepts identical parameters and returns the model's text response.
    """
    llm = get_llm(api_key, provider, base_url, model)

    if response_format:
        llm = llm.bind(response_format=response_format)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]

    try:
        response = llm.invoke(messages)
        return response.content
    except Exception as e:
        print(f"LangChain LLM error (provider={provider}): {e}")
        raise
