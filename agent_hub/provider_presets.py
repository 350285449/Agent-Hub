from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


OPENAI_COMPATIBLE_PROVIDER_TYPES = {
    "openai-compatible",
    "lm-studio",
    "vllm",
    "localai",
    "llama-cpp",
    "ollama",
    "ollama-local",
    "ollama-cloud",
    "groq",
    "openrouter",
    "cerebras",
    "together",
    "fireworks",
    "deepinfra",
    "mistral",
    "sambanova",
    "nvidia-nim",
    "github-models",
    "google-ai-studio",
    "huggingface",
    "cloudflare-workers-ai",
    "hyperbolic",
    "featherless",
    "replicate",
    "novita",
    "kluster",
    "parasail",
    "anyscale",
}


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    """Static provider defaults used to build editable agent configs."""

    provider_type: str
    display_name: str
    provider: str = "openai-compatible"
    base_url: str | None = None
    api_key_env: str | None = None
    chat_completions_path: str | None = None
    free: bool = True
    default_headers: dict[str, str] = field(default_factory=dict)
    supports_tools: bool | None = None
    supports_json: bool | None = None
    supports_streaming: bool | None = None
    supports_vision: bool | None = None
    supports_function_calling: bool | None = None
    notes: str = ""


@dataclass(frozen=True, slots=True)
class ProviderPreset:
    """A concrete provider/model pairing that can be copied into config."""

    name: str
    provider_type: str
    model: str
    display_name: str
    free: bool = True
    enabled: bool = False
    coding_score: float | None = None
    reasoning_score: float | None = None
    speed_score: float | None = None
    context_window: int | None = None
    supports_tools: bool | None = None
    supports_json: bool | None = None
    supports_streaming: bool | None = None
    supports_vision: bool | None = None
    supports_function_calling: bool | None = None
    priority: float | None = None
    notes: str = ""


PROVIDER_METADATA: dict[str, ProviderMetadata] = {
    "openai-compatible": ProviderMetadata(
        provider_type="openai-compatible",
        display_name="OpenAI-compatible endpoint",
        base_url=None,
        free=False,
        notes="Generic adapter for local servers, gateways, and hosted OpenAI-compatible APIs.",
    ),
    "lm-studio": ProviderMetadata(
        provider_type="lm-studio",
        display_name="LM Studio",
        base_url=os.environ.get("AGENT_HUB_LM_STUDIO_BASE_URL", "http://127.0.0.1:1234"),
        free=True,
        supports_json=True,
        supports_streaming=True,
        notes="Local LM Studio server using its OpenAI-compatible API.",
    ),
    "vllm": ProviderMetadata(
        provider_type="vllm",
        display_name="vLLM OpenAI-compatible server",
        base_url=os.environ.get("AGENT_HUB_VLLM_BASE_URL", "http://127.0.0.1:8000"),
        free=True,
        supports_tools=True,
        supports_json=True,
        supports_streaming=True,
        notes="Local or self-hosted vLLM endpoint using OpenAI-compatible chat completions.",
    ),
    "localai": ProviderMetadata(
        provider_type="localai",
        display_name="LocalAI",
        base_url=os.environ.get("AGENT_HUB_LOCALAI_BASE_URL", "http://127.0.0.1:8080"),
        free=True,
        supports_json=True,
        supports_streaming=True,
        notes="LocalAI OpenAI-compatible server.",
    ),
    "llama-cpp": ProviderMetadata(
        provider_type="llama-cpp",
        display_name="llama.cpp server",
        base_url=os.environ.get("AGENT_HUB_LLAMA_CPP_BASE_URL", "http://127.0.0.1:8080"),
        free=True,
        supports_json=True,
        supports_streaming=True,
        notes="llama.cpp server with OpenAI-compatible endpoints enabled.",
    ),
    "ollama-cloud": ProviderMetadata(
        provider_type="ollama-cloud",
        display_name="Ollama Cloud via Ollama API",
        base_url=os.environ.get("AGENT_HUB_OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        free=True,
        supports_streaming=True,
        supports_json=True,
    ),
    "codex-cli": ProviderMetadata(
        provider_type="codex-cli",
        display_name="Codex CLI authenticated with ChatGPT",
        provider="codex-cli",
        free=True,
        supports_tools=False,
        supports_json=True,
        supports_streaming=False,
        supports_vision=True,
        notes="Runs `codex exec` locally and reuses the Codex CLI login instead of an OpenAI API key.",
    ),
    "groq": ProviderMetadata(
        provider_type="groq",
        display_name="Groq",
        base_url="https://api.groq.com/openai/v1",
        api_key_env="GROQ_API_KEY",
        supports_tools=True,
        supports_json=True,
        supports_streaming=True,
    ),
    "openrouter": ProviderMetadata(
        provider_type="openrouter",
        display_name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        supports_tools=True,
        supports_json=True,
        supports_streaming=True,
        default_headers={
            "HTTP-Referer": "${AGENT_HUB_HTTP_REFERER:-http://localhost:8787}",
            "X-Title": "${AGENT_HUB_X_TITLE:-Agent Hub}",
        },
        notes="Free model IDs often end in :free and change over time.",
    ),
    "cerebras": ProviderMetadata(
        provider_type="cerebras",
        display_name="Cerebras Inference",
        base_url="https://api.cerebras.ai/v1",
        api_key_env="CEREBRAS_API_KEY",
        supports_json=True,
        supports_streaming=True,
    ),
    "together": ProviderMetadata(
        provider_type="together",
        display_name="Together AI",
        base_url="https://api.together.ai/v1",
        api_key_env="TOGETHER_API_KEY",
        supports_tools=True,
        supports_json=True,
        supports_streaming=True,
        supports_vision=False,
    ),
    "fireworks": ProviderMetadata(
        provider_type="fireworks",
        display_name="Fireworks AI",
        base_url="https://api.fireworks.ai/inference/v1",
        api_key_env="FIREWORKS_API_KEY",
        supports_tools=True,
        supports_json=True,
        supports_streaming=True,
        supports_vision=False,
    ),
    "deepinfra": ProviderMetadata(
        provider_type="deepinfra",
        display_name="DeepInfra",
        base_url="https://api.deepinfra.com/v1/openai",
        api_key_env="DEEPINFRA_API_KEY",
        supports_json=True,
        supports_streaming=True,
        supports_vision=False,
    ),
    "mistral": ProviderMetadata(
        provider_type="mistral",
        display_name="Mistral",
        base_url="https://api.mistral.ai/v1",
        api_key_env="MISTRAL_API_KEY",
        supports_tools=True,
        supports_json=True,
        supports_streaming=True,
    ),
    "sambanova": ProviderMetadata(
        provider_type="sambanova",
        display_name="SambaNova",
        base_url="https://api.sambanova.ai/v1",
        api_key_env="SAMBANOVA_API_KEY",
        supports_json=True,
        supports_streaming=True,
    ),
    "nvidia-nim": ProviderMetadata(
        provider_type="nvidia-nim",
        display_name="NVIDIA NIM",
        base_url="https://integrate.api.nvidia.com/v1",
        api_key_env="NVIDIA_API_KEY",
        supports_tools=True,
        supports_json=True,
        supports_streaming=True,
    ),
    "github-models": ProviderMetadata(
        provider_type="github-models",
        display_name="GitHub Models",
        base_url="https://models.github.ai/inference",
        api_key_env="GITHUB_TOKEN",
        chat_completions_path="/chat/completions",
        default_headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "${GITHUB_API_VERSION:-2026-03-10}",
        },
        supports_json=True,
        supports_streaming=True,
    ),
    "google-ai-studio": ProviderMetadata(
        provider_type="google-ai-studio",
        display_name="Gemini / Google AI Studio",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key_env="GEMINI_API_KEY",
        chat_completions_path="/chat/completions",
        supports_tools=True,
        supports_json=True,
        supports_streaming=True,
        supports_vision=False,
        supports_function_calling=True,
    ),
    "huggingface": ProviderMetadata(
        provider_type="huggingface",
        display_name="Hugging Face Inference Providers",
        base_url="https://router.huggingface.co/v1",
        api_key_env="HUGGINGFACE_API_KEY",
        supports_tools=True,
        supports_json=True,
        supports_streaming=True,
    ),
    "cloudflare-workers-ai": ProviderMetadata(
        provider_type="cloudflare-workers-ai",
        display_name="Cloudflare Workers AI / AI Gateway",
        base_url="https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/ai/v1",
        api_key_env="CLOUDFLARE_API_TOKEN",
        supports_json=True,
        supports_streaming=True,
        notes="Set CLOUDFLARE_ACCOUNT_ID or override base_url in config.",
    ),
    "hyperbolic": ProviderMetadata(
        provider_type="hyperbolic",
        display_name="Hyperbolic",
        base_url="https://api.hyperbolic.xyz/v1",
        api_key_env="HYPERBOLIC_API_KEY",
        supports_json=True,
        supports_streaming=True,
    ),
    "featherless": ProviderMetadata(
        provider_type="featherless",
        display_name="Featherless",
        base_url="https://api.featherless.ai/v1",
        api_key_env="FEATHERLESS_API_KEY",
        supports_json=True,
        supports_streaming=True,
        supports_vision=False,
        default_headers={
            "HTTP-Referer": "${AGENT_HUB_HTTP_REFERER:-http://localhost:8787}",
            "X-Title": "${AGENT_HUB_X_TITLE:-Agent Hub}",
        },
    ),
    "replicate": ProviderMetadata(
        provider_type="replicate",
        display_name="Replicate",
        base_url=None,
        api_key_env="REPLICATE_API_TOKEN",
        notes="Replicate's native API is prediction-based; set base_url only when using an OpenAI-compatible Replicate gateway.",
    ),
    "novita": ProviderMetadata(
        provider_type="novita",
        display_name="Novita AI",
        base_url="https://api.novita.ai/openai",
        api_key_env="NOVITA_API_KEY",
        supports_json=True,
        supports_streaming=True,
        supports_vision=False,
    ),
    "kluster": ProviderMetadata(
        provider_type="kluster",
        display_name="kluster.ai",
        base_url=None,
        api_key_env="KLUSTER_API_KEY",
        notes="kluster.ai is primarily an external code-review tool; set base_url if you expose an OpenAI-compatible chat gateway.",
    ),
    "parasail": ProviderMetadata(
        provider_type="parasail",
        display_name="Parasail",
        base_url="https://api.parasail.io/v1",
        api_key_env="PARASAIL_API_KEY",
        supports_json=True,
        supports_streaming=True,
    ),
    "anyscale": ProviderMetadata(
        provider_type="anyscale",
        display_name="Anyscale Endpoints",
        base_url="https://api.endpoints.anyscale.com/v1",
        api_key_env="ANYSCALE_API_KEY",
        supports_json=True,
        supports_streaming=True,
    ),
}


FREE_PROVIDER_PRESETS: list[ProviderPreset] = [
    ProviderPreset(
        name="ollama-glm-cloud",
        provider_type="ollama-cloud",
        model="glm-5.1:cloud",
        display_name="Ollama Cloud GLM 5.1",
        reasoning_score=0.8,
        coding_score=0.65,
        speed_score=0.5,
        context_window=128_000,
        priority=60,
    ),
    ProviderPreset(
        name="ollama-qwen-cloud",
        provider_type="ollama-cloud",
        model="qwen3.5:cloud",
        display_name="Ollama Cloud Qwen 3.5",
        reasoning_score=0.75,
        coding_score=0.8,
        speed_score=0.55,
        context_window=128_000,
        priority=60,
    ),
    ProviderPreset(
        name="ollama-nemotron-cloud",
        provider_type="ollama-cloud",
        model="nemotron-3-super:cloud",
        display_name="Ollama Cloud Nemotron 3 Super",
        reasoning_score=0.85,
        coding_score=0.7,
        speed_score=0.45,
        context_window=128_000,
        priority=55,
    ),
    ProviderPreset(
        name="ollama-gemma-cloud",
        provider_type="ollama-cloud",
        model="gemma4:31b-cloud",
        display_name="Ollama Cloud Gemma 4 31B",
        reasoning_score=0.65,
        coding_score=0.6,
        speed_score=0.6,
        context_window=128_000,
        priority=50,
    ),
    ProviderPreset(
        name="groq-llama-3-3-70b",
        provider_type="groq",
        model="llama-3.3-70b-versatile",
        display_name="Groq Llama 3.3 70B Versatile",
        reasoning_score=0.82,
        coding_score=0.72,
        speed_score=0.95,
        context_window=128_000,
        priority=70,
    ),
    ProviderPreset(
        name="groq-deepseek-r1-distill",
        provider_type="groq",
        model="deepseek-r1-distill-llama-70b",
        display_name="Groq DeepSeek R1 Distill Llama 70B",
        reasoning_score=0.9,
        coding_score=0.78,
        speed_score=0.85,
        context_window=128_000,
        priority=72,
    ),
    ProviderPreset(
        name="groq-qwen3-32b",
        provider_type="groq",
        model="qwen/qwen3-32b",
        display_name="Groq Qwen3 32B",
        reasoning_score=0.82,
        coding_score=0.84,
        speed_score=0.9,
        context_window=128_000,
        priority=74,
    ),
    ProviderPreset(
        name="openrouter-deepseek-free",
        provider_type="openrouter",
        model="deepseek/deepseek-r1:free",
        display_name="OpenRouter DeepSeek free slot",
        reasoning_score=0.9,
        coding_score=0.82,
        speed_score=0.5,
        context_window=64_000,
        priority=65,
        notes="OpenRouter free IDs change often; edit model if unavailable.",
    ),
    ProviderPreset(
        name="openrouter-qwen-free",
        provider_type="openrouter",
        model="qwen/qwen3-coder:free",
        display_name="OpenRouter Qwen coder free slot",
        reasoning_score=0.78,
        coding_score=0.9,
        speed_score=0.5,
        context_window=64_000,
        priority=66,
        notes="OpenRouter free IDs change often; edit model if unavailable.",
    ),
    ProviderPreset(
        name="openrouter-mistral-free",
        provider_type="openrouter",
        model="mistralai/mistral-small-3.2-24b-instruct:free",
        display_name="OpenRouter Mistral free slot",
        reasoning_score=0.7,
        coding_score=0.68,
        speed_score=0.55,
        context_window=32_000,
        priority=58,
        notes="OpenRouter free IDs change often; edit model if unavailable.",
    ),
    ProviderPreset(
        name="cerebras-llama-3-3-70b",
        provider_type="cerebras",
        model="llama-3.3-70b",
        display_name="Cerebras Llama 3.3 70B",
        reasoning_score=0.78,
        coding_score=0.68,
        speed_score=0.95,
        context_window=128_000,
        priority=68,
    ),
    ProviderPreset(
        name="gemini-2-5-flash",
        provider_type="google-ai-studio",
        model="gemini-2.5-flash",
        display_name="Gemini 2.5 Flash",
        reasoning_score=0.82,
        coding_score=0.78,
        speed_score=0.82,
        context_window=1_000_000,
        supports_tools=True,
        supports_vision=False,
        supports_function_calling=True,
        priority=76,
    ),
    ProviderPreset(
        name="gemini-2-5-pro",
        provider_type="google-ai-studio",
        model="gemini-2.5-pro",
        display_name="Gemini 2.5 Pro",
        reasoning_score=0.94,
        coding_score=0.86,
        speed_score=0.45,
        context_window=1_000_000,
        supports_tools=True,
        supports_vision=False,
        supports_function_calling=True,
        priority=78,
        notes="Availability and free quota may vary by account.",
    ),
    ProviderPreset(
        name="mistral-small-latest",
        provider_type="mistral",
        model="mistral-small-latest",
        display_name="Mistral Small latest",
        reasoning_score=0.72,
        coding_score=0.66,
        speed_score=0.75,
        context_window=128_000,
        priority=58,
    ),
    ProviderPreset(
        name="github-models-qwen3-coder",
        provider_type="github-models",
        model="qwen/qwen3-coder-30b-a3b-instruct",
        display_name="GitHub Models Qwen3 Coder",
        reasoning_score=0.78,
        coding_score=0.86,
        speed_score=0.6,
        context_window=128_000,
        priority=62,
        notes="GitHub Models catalog changes; edit model if your token exposes a different ID.",
    ),
    ProviderPreset(
        name="huggingface-qwen3-coder",
        provider_type="huggingface",
        model="Qwen/Qwen3-Coder-30B-A3B-Instruct",
        display_name="Hugging Face Qwen3 Coder",
        reasoning_score=0.78,
        coding_score=0.86,
        speed_score=0.45,
        context_window=64_000,
        priority=54,
    ),
    ProviderPreset(
        name="together-qwen3-coder",
        provider_type="together",
        model="Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8",
        display_name="Together Qwen3 Coder",
        reasoning_score=0.86,
        coding_score=0.92,
        speed_score=0.55,
        context_window=262_144,
        supports_tools=True,
        supports_vision=False,
        priority=60,
        notes="Together model names and free-tier access vary; edit model if unavailable.",
    ),
    ProviderPreset(
        name="fireworks-qwen3-coder",
        provider_type="fireworks",
        model="accounts/fireworks/models/qwen3-coder-480b-a35b-instruct",
        display_name="Fireworks Qwen3 Coder",
        reasoning_score=0.86,
        coding_score=0.92,
        speed_score=0.65,
        context_window=262_144,
        supports_tools=True,
        supports_vision=False,
        priority=61,
        notes="Fireworks model names and free-tier access vary; edit model if unavailable.",
    ),
    ProviderPreset(
        name="deepinfra-qwen3-coder",
        provider_type="deepinfra",
        model="Qwen/Qwen3-Coder-480B-A35B-Instruct",
        display_name="DeepInfra Qwen3 Coder",
        reasoning_score=0.84,
        coding_score=0.9,
        speed_score=0.5,
        context_window=262_144,
        supports_vision=False,
        priority=57,
        notes="DeepInfra model names and free-tier access vary; edit model if unavailable.",
    ),
    ProviderPreset(
        name="sambanova-llama-3-3-70b",
        provider_type="sambanova",
        model="Meta-Llama-3.3-70B-Instruct",
        display_name="SambaNova Llama 3.3 70B",
        reasoning_score=0.8,
        coding_score=0.72,
        speed_score=0.8,
        context_window=128_000,
        priority=56,
        notes="SambaNova catalog and free-tier access vary; edit model if unavailable.",
    ),
    ProviderPreset(
        name="nvidia-nemotron",
        provider_type="nvidia-nim",
        model="nvidia/llama-3.1-nemotron-70b-instruct",
        display_name="NVIDIA Nemotron 70B",
        reasoning_score=0.82,
        coding_score=0.72,
        speed_score=0.72,
        context_window=131_072,
        priority=64,
    ),
    ProviderPreset(
        name="cloudflare-llama-3-1-8b",
        provider_type="cloudflare-workers-ai",
        model="@cf/meta/llama-3.1-8b-instruct",
        display_name="Cloudflare Workers AI Llama 3.1 8B",
        reasoning_score=0.55,
        coding_score=0.45,
        speed_score=0.8,
        context_window=8_192,
        priority=40,
        notes="Set CLOUDFLARE_ACCOUNT_ID or override base_url before enabling.",
    ),
    ProviderPreset(
        name="hyperbolic-qwen3-coder",
        provider_type="hyperbolic",
        model="Qwen/Qwen3-Coder-480B-A35B-Instruct",
        display_name="Hyperbolic Qwen3 Coder",
        reasoning_score=0.84,
        coding_score=0.9,
        speed_score=0.5,
        context_window=262_144,
        priority=52,
        notes="Hyperbolic model names and free-tier access vary; edit model if unavailable.",
    ),
    ProviderPreset(
        name="featherless-qwen3-coder",
        provider_type="featherless",
        model="Qwen/Qwen3-Coder-30B-A3B-Instruct",
        display_name="Featherless Qwen3 Coder",
        reasoning_score=0.78,
        coding_score=0.86,
        speed_score=0.45,
        context_window=64_000,
        supports_vision=False,
        priority=50,
        notes="Featherless model names and free-tier access vary; edit model if unavailable.",
    ),
    ProviderPreset(
        name="novita-qwen3-coder",
        provider_type="novita",
        model="qwen/qwen3-coder-30b-a3b-instruct",
        display_name="Novita Qwen3 Coder",
        reasoning_score=0.78,
        coding_score=0.86,
        speed_score=0.55,
        context_window=64_000,
        supports_vision=False,
        priority=50,
        notes="Novita model names and free-tier access vary; edit model if unavailable.",
    ),
    ProviderPreset(
        name="parasail-qwen3-coder",
        provider_type="parasail",
        model="Qwen/Qwen3-Coder-30B-A3B-Instruct",
        display_name="Parasail Qwen3 Coder",
        reasoning_score=0.78,
        coding_score=0.86,
        speed_score=0.5,
        context_window=64_000,
        priority=48,
        notes="Parasail model names and free-tier access vary; edit model if unavailable.",
    ),
    ProviderPreset(
        name="anyscale-llama-3-1-70b",
        provider_type="anyscale",
        model="meta-llama/Meta-Llama-3.1-70B-Instruct",
        display_name="Anyscale Llama 3.1 70B",
        reasoning_score=0.78,
        coding_score=0.68,
        speed_score=0.55,
        context_window=128_000,
        priority=45,
        notes="Anyscale endpoint availability varies; edit model if unavailable.",
    ),
    ProviderPreset(
        name="replicate-openai-compatible",
        provider_type="replicate",
        model="replace-with-openai-compatible-replicate-model",
        display_name="Replicate OpenAI-compatible gateway",
        reasoning_score=0.5,
        coding_score=0.5,
        speed_score=0.4,
        context_window=8_192,
        priority=30,
        notes="Replicate native predictions need a gateway; set base_url before enabling.",
    ),
    ProviderPreset(
        name="kluster-external-review",
        provider_type="kluster",
        model="replace-with-openai-compatible-kluster-model",
        display_name="kluster.ai external review gateway",
        reasoning_score=0.6,
        coding_score=0.5,
        speed_score=0.5,
        context_window=8_192,
        priority=30,
        notes="kluster.ai is primarily external code review; set base_url before enabling.",
    ),
]


FREE_PROVIDER_PRESETS_BY_NAME: dict[str, ProviderPreset] = {
    preset.name: preset for preset in FREE_PROVIDER_PRESETS
}


def provider_metadata(provider_type: str | None) -> ProviderMetadata | None:
    if not provider_type:
        return None
    return PROVIDER_METADATA.get(provider_type.lower())


def provider_preset(name: str | None) -> ProviderPreset | None:
    if not name:
        return None
    return FREE_PROVIDER_PRESETS_BY_NAME.get(str(name).strip())


def provider_metadata_rows() -> list[dict[str, Any]]:
    return [
        {
            "provider_type": item.provider_type,
            "display_name": item.display_name,
            "provider": item.provider,
            "base_url": item.base_url,
            "api_key_env": item.api_key_env,
            "free": item.free,
            "supports_tools": item.supports_tools,
            "supports_json": item.supports_json,
            "supports_streaming": item.supports_streaming,
            "supports_vision": item.supports_vision,
            "notes": item.notes,
        }
        for item in PROVIDER_METADATA.values()
    ]


def preset_rows() -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "provider_type": item.provider_type,
            "model": item.model,
            "free": item.free,
            "enabled": item.enabled,
            "coding_score": item.coding_score,
            "reasoning_score": item.reasoning_score,
            "speed_score": item.speed_score,
            "context_window": item.context_window,
            "notes": item.notes,
        }
        for item in FREE_PROVIDER_PRESETS
    ]


def agent_dict_from_preset(preset: ProviderPreset, *, enabled: bool | None = None) -> dict[str, Any]:
    metadata = provider_metadata(preset.provider_type)
    provider = metadata.provider if metadata else "openai-compatible"
    data: dict[str, Any] = {
        "name": preset.name,
        "provider": provider,
        "provider_type": preset.provider_type,
        "model": preset.model,
        "enabled": preset.enabled if enabled is None else enabled,
        "free": preset.free,
        "api_key_env": metadata.api_key_env if metadata else None,
        "base_url": metadata.base_url if metadata else None,
        "headers": dict(metadata.default_headers) if metadata else {},
        "chat_completions_path": metadata.chat_completions_path if metadata else None,
        "timeout_seconds": 120,
        "cooldown_seconds": 120,
        "context_window": preset.context_window,
        "coding_score": preset.coding_score,
        "reasoning_score": preset.reasoning_score,
        "speed_score": preset.speed_score,
        "supports_tools": _first_not_none(preset.supports_tools, metadata.supports_tools if metadata else None),
        "supports_json": _first_not_none(preset.supports_json, metadata.supports_json if metadata else None),
        "supports_streaming": _first_not_none(
            preset.supports_streaming,
            metadata.supports_streaming if metadata else None,
        ),
        "supports_vision": _first_not_none(preset.supports_vision, metadata.supports_vision if metadata else None),
        "supports_function_calling": _first_not_none(
            preset.supports_function_calling,
            metadata.supports_function_calling if metadata else None,
        ),
        "priority": preset.priority,
    }
    return {key: value for key, value in data.items() if value is not None and value != {}}


def provider_defaults_for_agent(agent: Any) -> ProviderMetadata | None:
    provider_type = getattr(agent, "provider_type", None) or getattr(agent, "provider", None)
    return provider_metadata(str(provider_type).lower() if provider_type else None)


def provider_kind_for_agent(agent: Any) -> str:
    provider_type = getattr(agent, "provider_type", None) or getattr(agent, "provider", "")
    return str(provider_type).lower()


def chat_completions_path_for_agent(agent: Any) -> str:
    configured = getattr(agent, "chat_completions_path", None)
    if configured:
        return str(configured)
    metadata = provider_defaults_for_agent(agent)
    if metadata and metadata.chat_completions_path:
        return metadata.chat_completions_path
    return "/v1/chat/completions"


def default_headers_for_agent(agent: Any) -> dict[str, str]:
    metadata = provider_defaults_for_agent(agent)
    if not metadata:
        return {}
    return {key: _expand_env_header(value) for key, value in metadata.default_headers.items()}


def _expand_env_header(value: str) -> str:
    if value.startswith("${") and value.endswith("}") and ":-" in value:
        name, fallback = value[2:-1].split(":-", 1)
        return os.environ.get(name, fallback)
    return os.path.expandvars(value)


def _first_not_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None
