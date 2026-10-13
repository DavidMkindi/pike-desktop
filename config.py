"""Central configuration for Pike.

Values are resolved in this order (first one wins):

1. Environment variables (or a local ``.env`` file).
2. The user settings file written by the app (``settings.json``).
3. Built-in defaults.

Pike talks to any **OpenAI-compatible** provider. A catalogue of well known
providers lives in :data:`PROVIDERS`; each entry bundles the correct base URL,
a link to where you create a key, and the current top models. Users pick a
provider on the Settings ▸ Connection page and paste their key - the base URL
is filled in automatically.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from threading import Lock
from typing import Any

try:  # Optional dependency: makes .env files "just work" when present.
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:  # pragma: no cover - dotenv is optional
    pass

APP_NAME = "Pike"
APP_VERSION = "1.0.0"

ROOT = Path(__file__).resolve().parent


def _user_data_dir() -> Path:
    """Return a writable per-user directory for settings/history."""
    override = os.environ.get("PIKE_DATA_DIR")
    if override:
        target = Path(override).expanduser()
    elif os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home())
        target = Path(base) / "Pike"
    elif os.uname().sysname == "Darwin":  # type: ignore[attr-defined]
        target = Path.home() / "Library" / "Application Support" / "Pike"
    else:
        target = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "pike"
    target.mkdir(parents=True, exist_ok=True)
    return target


DATA_DIR = _user_data_dir()
SETTINGS_FILE = DATA_DIR / "settings.json"
HISTORY_FILE = DATA_DIR / "history.sqlite3"

_SETTINGS_LOCK = Lock()

# Model catalogues were last verified against the live provider APIs on this
# date. The "Refresh models" button re-pulls the live list from the provider.
CATALOG_UPDATED = "2026-10-08"


# --------------------------------------------------------------------------- #
#  Provider catalogue                                                         #
# --------------------------------------------------------------------------- #
def _m(
    model_id: str,
    label: str,
    hint: str = "",
    badge: str = "",
    reasoning: bool = False,
    context: int = 0,
) -> dict[str, Any]:
    """Build one model entry for the provider catalogue."""
    return {
        "id": model_id,
        "label": label,
        "hint": hint,
        "badge": badge,
        "reasoning": reasoning,
        "context": context,
    }


# Providers are keyed by a stable id. ``env`` is the prefix used for the
# ``PIKE_<ENV>_API_KEY`` / ``PIKE_<ENV>_BASE_URL`` overrides.
PROVIDERS: dict[str, dict[str, Any]] = {
    # ------------------------------------------------------------------ #
    #  tokenharbor.ai (built-in free tier)                                #
    # ------------------------------------------------------------------ #
    "tokenharbor": {
        "name": "tokenharbor.ai",
        "base_url": "https://tokenharbor.ai/v1",
        "docs_url": "https://tokenharbor.ai",
        "key_hint": "thk_live_...",
        "env": "TOKENHARBOR",
        "api_key": "thk_live_gxt6R6KlgqIjF8zl5O0b19L0V8XvkcEWmSO_zl2MAQ-cpjux_wqcZoJ92jy_VR0k",
        "compat": {"supportsDeveloperRole": False},
        "models": [
            _m("deepseek-v4.1-flash:free", "deepseek-v4.1-flash:free", "Free - fast", "Free", False, 0),
        ],
    },
    # ------------------------------------------------------------------ #
    #  OpenAI                                                             #
    # ------------------------------------------------------------------ #
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "docs_url": "https://platform.openai.com/api-keys",
        "key_hint": "sk-...",
        "env": "OPENAI",
        "models": [
            _m("gpt-6.1-sol-pro", "GPT-6.1 Sol Pro", "Flagship reasoning", "New", True, 1050000),
            _m("gpt-6.1-sol", "GPT-6.1 Sol", "Frontier reasoning", "New", True, 1050000),
            _m("gpt-6-sol-pro", "GPT-6 Sol Pro", "Frontier reasoning", "", True, 1050000),
            _m("gpt-6-sol", "GPT-6 Sol", "Frontier reasoning", "", True, 1050000),
            _m("gpt-6-astra", "GPT-6 Astra", "Frontier reasoning", "", True, 1050000),
            _m("gpt-6-luna", "GPT-6 Luna", "Fast frontier", "", True, 1050000),
            _m("gpt-5.6-sol", "GPT-5.6 Sol", "Deep reasoning", "", True, 1050000),
            _m("gpt-5.6-terra", "GPT-5.6 Terra", "Balanced reasoning", "", True, 1050000),
            _m("gpt-5.6-luna", "GPT-5.6 Luna", "Fast reasoning", "", True, 1050000),
            _m("gpt-5.5-pro", "GPT-5.5 Pro", "Most capable", "", True, 1050000),
            _m("gpt-5.5", "GPT-5.5", "Previous frontier", "", True, 1050000),
            _m("gpt-5.4", "GPT-5.4", "General purpose", "", True, 1050000),
            _m("gpt-5.4-mini", "GPT-5.4 mini", "Fast & affordable", "", True, 400000),
            _m("gpt-5.4-nano", "GPT-5.4 nano", "Fastest & cheapest", "", True, 400000),
            _m("gpt-5.3-codex", "GPT-5.3 Codex", "Coding specialist", "", True, 400000),
            _m("gpt-5.2", "GPT-5.2", "General purpose", "", True, 400000),
            _m("gpt-5.1", "GPT-5.1", "General purpose", "", True, 400000),
            _m("gpt-5", "GPT-5", "Reasoning", "", True, 400000),
            _m("gpt-5-mini", "GPT-5 mini", "Fast reasoning", "", True, 400000),
            _m("gpt-5-nano", "GPT-5 nano", "Cheapest reasoning", "", True, 400000),
            _m("gpt-4.1", "GPT-4.1", "Long context - 1M", "", True, 1047576),
            _m("gpt-4.1-mini", "GPT-4.1 mini", "Balanced - 1M", "", True, 1047576),
            _m("gpt-4o", "GPT-4o", "Multimodal - 128K", "", False, 128000),
            _m("gpt-4o-mini", "GPT-4o mini", "Fast & affordable", "", False, 128000),
            _m("o3", "o3", "Reasoning", "", True, 200000),
            _m("o4-mini", "o4-mini", "Fast reasoning", "", True, 200000),
            _m("gpt-oss-120b", "GPT-OSS 120B", "Open-weight model", "", False, 131072),
        ],
    },
    # ------------------------------------------------------------------ #
    #  Anthropic (OpenAI-compatible endpoint)                             #
    # ------------------------------------------------------------------ #
    "anthropic": {
        "name": "Anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "docs_url": "https://console.anthropic.com/settings/keys",
        "key_hint": "sk-ant-...",
        "env": "ANTHROPIC",
        "models": [
            _m("claude-opus-5.5", "Claude Opus 5.5", "Most capable - 1M context", "New", True, 1000000),
            _m("claude-sonnet-5.5", "Claude Sonnet 5.5", "Balanced - 1M context", "New", True, 1000000),
            _m("claude-haiku-5.5", "Claude Haiku 5.5", "Fast & cheap - 1M context", "", True, 1000000),
            _m("claude-opus-5", "Claude Opus 5", "Deep reasoning - 1M", "", True, 1000000),
            _m("claude-sonnet-5", "Claude Sonnet 5", "Balanced - 1M", "", True, 1000000),
            _m("claude-opus-4.8", "Claude Opus 4.8", "Previous flagship", "", True, 1000000),
            _m("claude-sonnet-4.6", "Claude Sonnet 4.6", "Previous balanced", "", True, 1000000),
            _m("claude-opus-4.5", "Claude Opus 4.5", "Deep reasoning", "", True, 200000),
            _m("claude-haiku-4.5", "Claude Haiku 4.5", "Fast & cheap", "", True, 200000),
        ],
    },
    # ------------------------------------------------------------------ #
    #  Google Gemini (OpenAI-compatible endpoint)                         #
    # ------------------------------------------------------------------ #
    "google": {
        "name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "docs_url": "https://aistudio.google.com/app/apikey",
        "key_hint": "AIza...",
        "env": "GOOGLE",
        "models": [
            _m("gemini-3.8-flash", "Gemini 3.8 Flash", "Fast - 1M context", "New", True, 1048576),
            _m("gemini-3.7-flash", "Gemini 3.7 Flash", "Fast - 1M context", "", True, 1048576),
            _m("gemini-3.6-flash", "Gemini 3.6 Flash", "Fast - 1M context", "", True, 1048576),
            _m("gemini-3.5-flash", "Gemini 3.5 Flash", "Fast - 1M context", "", True, 1048576),
            _m("gemini-3.5-flash-lite", "Gemini 3.5 Flash Lite", "Cheapest - 1M", "", True, 1048576),
            _m("gemini-3.1-pro-preview", "Gemini 3.1 Pro", "Flagship - 1M context", "", True, 1048576),
            _m("gemini-3.1-flash-lite", "Gemini 3.1 Flash Lite", "Fast & cheap", "", True, 1048576),
            _m("gemini-2.5-pro", "Gemini 2.5 Pro", "Previous flagship", "", True, 1048576),
            _m("gemini-2.5-flash", "Gemini 2.5 Flash", "Previous fast", "", True, 1048576),
            _m("gemma-4-31b-it", "Gemma 4 31B", "Open model", "", False, 262144),
        ],
    },
    # ------------------------------------------------------------------ #
    #  xAI (Grok)                                                         #
    # ------------------------------------------------------------------ #
    "xai": {
        "name": "xAI (Grok)",
        "base_url": "https://api.x.ai/v1",
        "docs_url": "https://console.x.ai",
        "key_hint": "xai-...",
        "env": "XAI",
        "models": [
            _m("grok-4.7", "Grok 4.7", "Flagship - 500K context", "New", True, 500000),
            _m("grok-4.6", "Grok 4.6", "Frontier - 500K context", "", True, 500000),
            _m("grok-4.5", "Grok 4.5", "Frontier - 500K context", "", True, 500000),
            _m("grok-4.3", "Grok 4.3", "Frontier - 1M context", "", True, 1000000),
            _m("grok-4.20", "Grok 4.20", "Long context - 2M", "", True, 2000000),
            _m("grok-build-0.1", "Grok Build 0.1", "Coding specialist", "", True, 256000),
        ],
    },
    # ------------------------------------------------------------------ #
    #  DeepSeek                                                           #
    # ------------------------------------------------------------------ #
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "docs_url": "https://platform.deepseek.com/api_keys",
        "key_hint": "sk-...",
        "env": "DEEPSEEK",
        "models": [
            _m("deepseek-flash", "DeepSeek Flash", "Fast & affordable - 1M", "New", False, 1048576),
            _m("deepseek-v4-pro", "DeepSeek V4 Pro", "Deep reasoning - 1M", "New", True, 1048576),
            _m("deepseek-v3.2", "DeepSeek V3.2", "Previous generation", "", False, 163840),
            _m("deepseek-chat", "DeepSeek Chat", "General purpose", "", False, 163840),
            _m("deepseek-reasoner", "DeepSeek Reasoner", "Reasoning", "", True, 163840),
        ],
    },
    # ------------------------------------------------------------------ #
    #  Mistral                                                            #
    # ------------------------------------------------------------------ #
    "mistral": {
        "name": "Mistral AI",
        "base_url": "https://api.mistral.ai/v1",
        "docs_url": "https://console.mistral.ai/api-keys",
        "key_hint": "...",
        "env": "MISTRAL",
        "models": [
            _m("mistral-large-4", "Mistral Large 4", "Flagship - 512K context", "New", False, 524288),
            _m("mistral-medium-3.5", "Mistral Medium 3.5", "Balanced - 256K", "", False, 262144),
            _m("mistral-small-2603", "Mistral Small 2603", "Fast & cheap - 256K", "", False, 262144),
            _m("codestral-2508", "Codestral 2508", "Coding specialist - 256K", "", False, 256000),
            _m("devstral-2512", "Devstral 2512", "Agentic coding", "", False, 262144),
            _m("ministral-14b-2512", "Ministral 14B", "Small & fast", "", False, 262144),
            _m("mistral-large-2512", "Mistral Large 2512", "Previous flagship", "", False, 262144),
        ],
    },
    # ------------------------------------------------------------------ #
    #  Groq (fast open models)                                            #
    # ------------------------------------------------------------------ #
    "groq": {
        "name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "docs_url": "https://console.groq.com/keys",
        "key_hint": "gsk_...",
        "env": "GROQ",
        "models": [
            _m("llama-3.3-70b-versatile", "Llama 3.3 70B", "Fast open model - 128K", "", False, 131072),
            _m("llama-3.1-8b-instant", "Llama 3.1 8B Instant", "Ultra fast", "", False, 131072),
            _m("qwen-2.5-32b", "Qwen 2.5 32B", "Open model", "", False, 131072),
            _m("deepseek-r1-distill-llama-70b", "DeepSeek R1 Distill 70B", "Reasoning", "", True, 131072),
            _m("gemma2-9b-it", "Gemma 2 9B", "Small & fast", "", False, 8192),
        ],
    },
    # ------------------------------------------------------------------ #
    #  Together AI                                                        #
    # ------------------------------------------------------------------ #
    "together": {
        "name": "Together AI",
        "base_url": "https://api.together.xyz/v1",
        "docs_url": "https://api.together.ai/settings/api-keys",
        "key_hint": "...",
        "env": "TOGETHER",
        "models": [
            _m("meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8", "Llama 4 Maverick", "Open model - 1M", "", False, 1048576),
            _m("meta-llama/Llama-3.3-70B-Instruct-Turbo", "Llama 3.3 70B Turbo", "Fast open model", "", False, 131072),
            _m("Qwen/Qwen3-235B-A22B-Instruct-2507-tput", "Qwen3 235B", "Open flagship", "", False, 262144),
            _m("deepseek-ai/DeepSeek-R1", "DeepSeek R1", "Reasoning", "", True, 163840),
            _m("deepseek-ai/DeepSeek-V3", "DeepSeek V3", "Open model", "", False, 163840),
        ],
    },
    # ------------------------------------------------------------------ #
    #  OpenRouter (aggregator - one key, hundreds of models)              #
    # ------------------------------------------------------------------ #
    "openrouter": {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "docs_url": "https://openrouter.ai/keys",
        "key_hint": "sk-or-...",
        "env": "OPENROUTER",
        "models": [
            _m("openai/gpt-6.1-sol-pro", "OpenAI: GPT-6.1 Sol Pro", "Frontier reasoning", "New", True, 1050000),
            _m("openai/gpt-6.1-sol", "OpenAI: GPT-6.1 Sol", "Frontier reasoning", "New", True, 1050000),
            _m("openai/gpt-6-astra", "OpenAI: GPT-6 Astra", "Frontier reasoning", "", True, 1050000),
            _m("openai/gpt-6-luna", "OpenAI: GPT-6 Luna", "Fast frontier", "", True, 1050000),
            _m("openai/gpt-5.5", "OpenAI: GPT-5.5", "Previous frontier", "", True, 1050000),
            _m("anthropic/claude-opus-5.5", "Anthropic: Claude Opus 5.5", "Most capable", "New", True, 1000000),
            _m("anthropic/claude-sonnet-5.5", "Anthropic: Claude Sonnet 5.5", "Balanced", "New", True, 1000000),
            _m("anthropic/claude-haiku-5.5", "Anthropic: Claude Haiku 5.5", "Fast & cheap", "", True, 1000000),
            _m("google/gemini-3.8-flash", "Google: Gemini 3.8 Flash", "Fast - 1M", "New", True, 1048576),
            _m("google/gemini-3.1-pro-preview", "Google: Gemini 3.1 Pro", "Flagship - 1M", "", True, 1048576),
            _m("x-ai/grok-4.7", "xAI: Grok 4.7", "Frontier - 500K", "New", True, 500000),
            _m("deepseek/deepseek-v4.1-flash", "DeepSeek V4.1 Flash", "Fast & cheap - 1M", "", False, 1048576),
            _m("deepseek/deepseek-v4-pro", "DeepSeek V4 Pro", "Deep reasoning", "", True, 1048576),
            _m("z-ai/glm-5.3", "Z.ai: GLM-5.3", "Frontier - 1M", "", True, 1048576),
            _m("moonshotai/kimi-k3", "Moonshot: Kimi K3", "1M context", "", True, 1048576),
            _m("qwen/qwen3.8-max", "Qwen: Qwen3.8 Max", "Flagship", "", True, 1000000),
            _m("qwen/qwen3.8-flash", "Qwen: Qwen3.8 Flash", "Fast & cheap", "", False, 1000000),
            _m("meta-llama/llama-4-maverick", "Meta: Llama 4 Maverick", "Open model - 1M", "", False, 1048576),
            _m("mistralai/mistral-large-4-0", "Mistral: Large 4", "Flagship", "", False, 524288),
            _m("minimax/minimax-m3", "MiniMax M3", "1M context", "", False, 1048576),
            _m("google/gemma-4-31b-it:free", "Google: Gemma 4 31B", "Free open model", "Free", False, 262144),
            _m("nvidia/nemotron-3.5-lightning:free", "NVIDIA: Nemotron 3.5 Lightning", "Free - 1M", "Free", False, 1000000),
        ],
    },
    # ------------------------------------------------------------------ #
    #  Perplexity (search-augmented)                                      #
    # ------------------------------------------------------------------ #
    "perplexity": {
        "name": "Perplexity",
        "base_url": "https://api.perplexity.ai",
        "docs_url": "https://www.perplexity.ai/settings/api",
        "key_hint": "pplx-...",
        "env": "PERPLEXITY",
        "models": [
            _m("sonar-pro", "Sonar Pro", "Search + reasoning - 200K", "", False, 200000),
            _m("sonar", "Sonar", "Search-augmented - 127K", "", False, 127072),
            _m("sonar-reasoning-pro", "Sonar Reasoning Pro", "Deep research", "", True, 128000),
            _m("sonar-deep-research", "Sonar Deep Research", "Long-form research", "", True, 128000),
        ],
    },
    # ------------------------------------------------------------------ #
    #  Moonshot (Kimi)                                                    #
    # ------------------------------------------------------------------ #
    "moonshot": {
        "name": "Moonshot (Kimi)",
        "base_url": "https://api.moonshot.ai/v1",
        "docs_url": "https://platform.moonshot.ai/console/api-keys",
        "key_hint": "sk-...",
        "env": "MOONSHOT",
        "models": [
            _m("kimi-k3", "Kimi K3", "Flagship - 1M context", "New", True, 1048576),
            _m("kimi-k2.6", "Kimi K2.6", "Long context - 256K", "", True, 262144),
            _m("kimi-k2.5", "Kimi K2.5", "Long context - 256K", "", True, 262144),
            _m("kimi-k2-thinking", "Kimi K2 Thinking", "Reasoning - 256K", "", True, 262144),
        ],
    },
    # ------------------------------------------------------------------ #
    #  Z.ai (GLM)                                                         #
    # ------------------------------------------------------------------ #
    "zai": {
        "name": "Z.ai (GLM)",
        "base_url": "https://api.z.ai/api/paas/v4",
        "docs_url": "https://z.ai/manage-apikey/apikey-list",
        "key_hint": "...",
        "env": "ZAI",
        "models": [
            _m("glm-5.3", "GLM-5.3", "Frontier - 1M context", "New", True, 1048576),
            _m("glm-5.3-flash", "GLM-5.3 Flash", "Fast & cheap - 1M", "New", True, 1048576),
            _m("glm-5.2", "GLM-5.2", "Frontier - 1M", "", True, 1048576),
            _m("glm-5.1", "GLM-5.1", "Previous frontier", "", True, 204800),
            _m("glm-4.7", "GLM-4.7", "Previous generation", "", True, 204800),
            _m("glm-4.7-flash", "GLM-4.7 Flash", "Fast & cheap", "", True, 200000),
        ],
    },
    # ------------------------------------------------------------------ #
    #  Qwen / DashScope (Alibaba)                                         #
    # ------------------------------------------------------------------ #
    "qwen": {
        "name": "Qwen (Alibaba)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "docs_url": "https://bailian.console.alibabacloud.com",
        "key_hint": "sk-...",
        "env": "QWEN",
        "models": [
            _m("qwen3.8-max", "Qwen3.8 Max", "Flagship - 1M context", "New", True, 1000000),
            _m("qwen3.8-flash", "Qwen3.8 Flash", "Fast & cheap - 1M", "", False, 1000000),
            _m("qwen3.7-max", "Qwen3.7 Max", "Reasoning flagship", "", True, 1000000),
            _m("qwen3.7-plus", "Qwen3.7 Plus", "Balanced", "", False, 1000000),
            _m("qwen3.6-flash", "Qwen3.6 Flash", "Fast & cheap", "", False, 1000000),
            _m("qwen3-coder-plus", "Qwen3 Coder Plus", "Coding - 1M", "", False, 1000000),
            _m("qwen-max", "Qwen Max", "Previous flagship", "", False, 32768),
        ],
    },
    # ------------------------------------------------------------------ #
    #  Amazon Bedrock / Nova                                              #
    # ------------------------------------------------------------------ #
    "amazon": {
        "name": "Amazon Nova",
        "base_url": "https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1",
        "docs_url": "https://console.aws.amazon.com/bedrock",
        "key_hint": "Bedrock API key",
        "env": "AMAZON",
        "models": [
            _m("amazon.nova-premier-v1:0", "Nova Premier", "Most capable - 1M", "", True, 1000000),
            _m("amazon.nova-pro-v1:0", "Nova Pro", "Balanced - 300K", "", False, 300000),
            _m("amazon.nova-2-lite-v1:0", "Nova 2 Lite", "Fast - 1M", "", True, 1000000),
            _m("amazon.nova-lite-v1:0", "Nova Lite", "Fast & cheap", "", False, 300000),
        ],
    },
    # ------------------------------------------------------------------ #
    #  Cohere                                                             #
    # ------------------------------------------------------------------ #
    "cohere": {
        "name": "Cohere",
        "base_url": "https://api.cohere.ai/compatibility/v1",
        "docs_url": "https://dashboard.cohere.com/api-keys",
        "key_hint": "...",
        "env": "COHERE",
        "models": [
            _m("command-a-plus", "Command A Plus", "Flagship - 192K", "New", False, 192000),
            _m("command-a", "Command A", "Balanced - 256K", "", False, 256000),
            _m("command-r-plus-08-2024", "Command R+", "Previous", "", False, 128000),
            _m("command-r-08-2024", "Command R", "Fast & cheap", "", False, 128000),
        ],
    },
    # ------------------------------------------------------------------ #
    #  Cerebras (ultra-fast inference)                                    #
    # ------------------------------------------------------------------ #
    "cerebras": {
        "name": "Cerebras",
        "base_url": "https://api.cerebras.ai/v1",
        "docs_url": "https://cloud.cerebras.ai",
        "key_hint": "csk-...",
        "env": "CEREBRAS",
        "models": [
            _m("llama-3.3-70b", "Llama 3.3 70B", "Fast inference", "", False, 131072),
            _m("llama3.1-8b", "Llama 3.1 8B", "Ultra fast", "", False, 131072),
            _m("qwen-3-32b", "Qwen 3 32B", "Fast reasoning", "", True, 131072),
        ],
    },
    # ------------------------------------------------------------------ #
    #  Local / self-hosted (Ollama, LM Studio, vLLM, ...)                 #
    # ------------------------------------------------------------------ #
    "ollama": {
        "name": "Ollama (local)",
        "base_url": "http://localhost:11434/v1",
        "docs_url": "https://ollama.com/download",
        "key_hint": "ollama",
        "env": "OLLAMA",
        "models": [
            _m("llama3.2", "Llama 3.2 (local)", "Pull with: ollama pull llama3.2", "", False, 131072),
            _m("qwen2.5", "Qwen 2.5 (local)", "Pull with: ollama pull qwen2.5", "", False, 32768),
            _m("deepseek-r1", "DeepSeek R1 (local)", "Pull with: ollama pull deepseek-r1", "", True, 131072),
        ],
    },
    "lmstudio": {
        "name": "LM Studio (local)",
        "base_url": "http://localhost:1234/v1",
        "docs_url": "https://lmstudio.ai",
        "key_hint": "lm-studio",
        "env": "LMSTUDIO",
        "models": [
            _m("local-model", "Loaded model", "The model loaded in LM Studio", "", False, 0),
        ],
    },
    # ------------------------------------------------------------------ #
    #  Custom OpenAI-compatible endpoint                                  #
    # ------------------------------------------------------------------ #
    "custom": {
        "name": "Custom (OpenAI-compatible)",
        "base_url": "",
        "docs_url": "",
        "key_hint": "your API key",
        "env": "CUSTOM",
        "models": [],
    },
}

# Providers that ship with a usable key and need no user configuration.
BUILTIN_PROVIDER = ""
DEFAULT_PROVIDER = "openai"

# Providers surfaced first in the Settings picker (the rest are still listed).
FEATURED_PROVIDERS = [
    "tokenharbor",
    "openai",
    "anthropic",
    "google",
    "xai",
    "deepseek",
    "mistral",
    "groq",
    "openrouter",
    "perplexity",
    "moonshot",
    "zai",
    "qwen",
    "together",
    "cohere",
    "cerebras",
    "amazon",
    "ollama",
    "lmstudio",
    "custom",
]

_SENSITIVE_KEYS = {"api_key", "provider_api_keys"}


# --------------------------------------------------------------------------- #
#  Settings file                                                              #
# --------------------------------------------------------------------------- #
def _read_settings() -> dict[str, Any]:
    if not SETTINGS_FILE.is_file():
        return {}
    try:
        data = json.loads(SETTINGS_FILE.read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_settings() -> dict[str, Any]:
    """Return the stored settings (secrets redacted for safe display)."""
    with _SETTINGS_LOCK:
        raw = _read_settings()
    safe = {k: v for k, v in raw.items() if k not in _SENSITIVE_KEYS}
    safe["has_api_key"] = bool(raw.get("api_key"))
    return safe


def _write_settings(data: dict[str, Any]) -> None:
    with _SETTINGS_LOCK:
        current = _read_settings()
        current.update(data)
        SETTINGS_FILE.write_text(json.dumps(current, indent=2), "utf-8")
        try:
            os.chmod(SETTINGS_FILE, 0o600)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
#  Active provider + credentials                                              #
# --------------------------------------------------------------------------- #
def get_active_provider() -> str:
    """The provider id the user last selected (env override wins)."""
    override = os.environ.get("PIKE_PROVIDER")
    if override and override.strip() in PROVIDERS:
        return override.strip()
    with _SETTINGS_LOCK:
        stored = _read_settings().get("provider")
    if isinstance(stored, str) and stored.strip() in PROVIDERS:
        return stored.strip()
    return DEFAULT_PROVIDER


def set_active_provider(provider: str | None) -> None:
    value = (provider or "").strip()
    if value in PROVIDERS:
        _write_settings({"provider": value})


def _provider_api_keys() -> dict[str, str]:
    with _SETTINGS_LOCK:
        stored = _read_settings().get("provider_api_keys")
    if not isinstance(stored, dict):
        return {}
    return {k: v for k, v in stored.items() if isinstance(v, str)}


def get_provider_key(provider: str) -> str:
    """Resolve the API key for a provider (env > stored per-provider > built-in)."""
    entry = PROVIDERS.get(provider, {})
    env = entry.get("env", "")
    if env:
        value = os.environ.get(f"PIKE_{env}_API_KEY")
        if value and value.strip():
            return value.strip()
        # OPENAI-style aliases for the common providers.
    if provider == "openai":
        value = os.environ.get("OPENAI_API_KEY")
        if value and value.strip():
            return value.strip()
    stored = _provider_api_keys().get(provider)
    if stored and stored.strip():
        return stored.strip()
    # Legacy single-key setting applies to the active provider.
    if provider == get_active_provider():
        with _SETTINGS_LOCK:
            legacy = _read_settings().get("api_key")
        if isinstance(legacy, str) and legacy.strip():
            return legacy.strip()
    return str(entry.get("api_key") or "").strip()


def provider_has_key(provider: str) -> bool:
    return bool(get_provider_key(provider))


def save_provider_key(provider: str, key: str | None) -> None:
    """Persist (or clear) the API key for a specific provider."""
    if provider not in PROVIDERS:
        return
    with _SETTINGS_LOCK:
        current = _read_settings()
        keys = current.get("provider_api_keys")
        keys = dict(keys) if isinstance(keys, dict) else {}
        if key and key.strip():
            keys[provider] = key.strip()
        else:
            keys.pop(provider, None)
        current["provider_api_keys"] = keys
        SETTINGS_FILE.write_text(json.dumps(current, indent=2), "utf-8")
        try:
            os.chmod(SETTINGS_FILE, 0o600)
        except OSError:
            pass


# Legacy helpers (kept for backwards compatibility / env vars). --------------- #
def get_api_key() -> str:
    """Resolve the API key for the active provider."""
    return get_provider_key(get_active_provider())


def save_api_key(key: str | None) -> None:
    """Persist (or clear) the key for the active provider."""
    save_provider_key(get_active_provider(), key)


def get_base_url() -> str:
    """Resolve the base URL for the active provider (env override wins)."""
    return get_provider_base_url(get_active_provider())


def set_base_url(url: str | None) -> None:
    """Store a custom base URL override for the active provider."""
    provider = get_active_provider()
    with _SETTINGS_LOCK:
        current = _read_settings()
        overrides = current.get("provider_base_urls")
        overrides = dict(overrides) if isinstance(overrides, dict) else {}
        value = (url or "").strip().rstrip("/")
        if value:
            overrides[provider] = value
        else:
            overrides.pop(provider, None)
        current["provider_base_urls"] = overrides
        SETTINGS_FILE.write_text(json.dumps(current, indent=2), "utf-8")


def get_provider_base_url(provider: str) -> str:
    entry = PROVIDERS.get(provider, {})
    env = entry.get("env", "")
    if env:
        value = os.environ.get(f"PIKE_{env}_BASE_URL")
        if value and value.strip():
            return value.strip().rstrip("/")
    if provider == "openai":
        value = os.environ.get("OPENAI_BASE_URL")
        if value and value.strip():
            return value.strip().rstrip("/")
    with _SETTINGS_LOCK:
        overrides = _read_settings().get("provider_base_urls")
    if isinstance(overrides, dict):
        stored = overrides.get(provider)
        if isinstance(stored, str) and stored.strip():
            return stored.strip().rstrip("/")
    return str(entry.get("base_url") or "").strip().rstrip("/")


def _provider_env_slug(name: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in name.upper())


# --------------------------------------------------------------------------- #
#  Model catalogue                                                            #
# --------------------------------------------------------------------------- #
def _catalog_cache() -> dict[str, list[dict[str, Any]]]:
    with _SETTINGS_LOCK:
        cached = _read_settings().get("model_catalog")
    return cached if isinstance(cached, dict) else {}


def save_catalog(provider: str, models: list[dict[str, Any]]) -> None:
    """Cache a freshly fetched model list for a provider."""
    if provider not in PROVIDERS or not isinstance(models, list):
        return
    cleaned: list[dict[str, Any]] = []
    for model in models:
        if not isinstance(model, dict) or not model.get("id"):
            continue
        cleaned.append(
            {
                "id": str(model["id"]),
                "label": str(model.get("label") or model["id"]),
                "hint": str(model.get("hint") or ""),
                "badge": str(model.get("badge") or ""),
                "reasoning": bool(model.get("reasoning")),
                "context": int(model.get("context") or 0),
            }
        )
    with _SETTINGS_LOCK:
        current = _read_settings()
        catalog = current.get("model_catalog")
        catalog = dict(catalog) if isinstance(catalog, dict) else {}
        catalog[provider] = {"updated": time.time(), "models": cleaned}
        current["model_catalog"] = catalog
        SETTINGS_FILE.write_text(json.dumps(current, indent=2), "utf-8")


def _models_for_provider(provider: str) -> list[dict[str, Any]]:
    """Built-in models first, then any cached live models that add new ids."""
    entry = PROVIDERS.get(provider, {})
    builtin = [dict(model) for model in entry.get("models", [])]
    seen = {model["id"] for model in builtin}
    cache = _catalog_cache().get(provider)
    if isinstance(cache, dict):
        for model in cache.get("models", []):
            if isinstance(model, dict) and model.get("id") and model["id"] not in seen:
                builtin.append(dict(model))
                seen.add(model["id"])
    return builtin


def provider_models(provider: str) -> list[dict[str, Any]]:
    """Every catalogued model of one provider, tagged with its provider."""
    models: list[dict[str, Any]] = []
    for model in _models_for_provider(provider):
        entry = dict(model)
        entry["provider"] = provider
        entry.setdefault("reasoning", False)
        models.append(entry)
    return models


def all_models() -> list[dict[str, Any]]:
    """Every model from every provider, tagged with its provider.

    The full catalogue is always returned so switching provider never hides
    models. Models whose provider has a saved API key can be used right away;
    the rest are shown too and simply prompt for a key when selected.
    """
    models: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for provider in FEATURED_PROVIDERS:
        if provider not in PROVIDERS:
            continue
        for model in provider_models(provider):
            key = (provider, str(model.get("id")))
            if key in seen:
                continue
            seen.add(key)
            model["has_key"] = provider_has_key(provider)
            model.setdefault("provider_name", PROVIDERS[provider].get("name", provider))
            models.append(model)
    return models


def get_models() -> list[dict[str, Any]]:
    """Models shown in the UI - the full cross-provider catalogue.

    ``PIKE_MODELS`` (a comma-separated ``id`` or ``id:Label`` list) overrides
    everything, which is handy for custom endpoints.
    """
    override = os.environ.get("PIKE_MODELS")
    if override:
        models: list[dict[str, Any]] = []
        for entry in override.split(","):
            entry = entry.strip()
            if not entry:
                continue
            if ":" in entry:
                model_id, label = entry.split(":", 1)
            else:
                model_id = label = entry
            models.append({
                "id": model_id.strip(),
                "label": label.strip(),
                "hint": "",
                "badge": "",
                "provider": get_active_provider(),
                "provider_name": PROVIDERS.get(get_active_provider(), {}).get("name", get_active_provider()),
                "has_key": provider_has_key(get_active_provider()),
                "reasoning": False,
                "context": 0,
            })
        if models:
            return models

    return all_models()


def _provider_for_model(model_id: str) -> str | None:
    """Find the provider that owns a model id (by catalogue or cached list)."""
    for provider in FEATURED_PROVIDERS:
        if provider not in PROVIDERS:
            continue
        for model in _models_for_provider(provider):
            if str(model.get("id")) == model_id:
                return provider
    return None


def resolve_connection(model_id: str | None = None) -> dict[str, Any]:
    """Resolve base URL, key and metadata for the given model id.

    The model's own provider wins, so selecting e.g. a Groq model routes to
    Groq. If no provider claims the id, the active provider is used (this is
    how custom / self-hosted endpoints work).
    """
    active = get_active_provider()
    chosen = (model_id or get_default_model()).strip()

    provider = _provider_for_model(chosen)
    if provider is None:
        provider = active

    base_url = get_provider_base_url(provider)
    api_key = get_provider_key(provider)

    meta = None
    for model in _models_for_provider(provider):
        if str(model.get("id")) == chosen:
            meta = dict(model)
            break
    if meta is None:
        meta = {"id": chosen, "label": chosen, "reasoning": False}

    return {
        "base_url": base_url,
        "api_key": api_key,
        "provider": provider,
        "model": meta,
    }


def available_providers() -> list[dict[str, Any]]:
    """Describe every provider and its current configuration state."""
    active = get_active_provider()
    result: list[dict[str, Any]] = []
    for key in FEATURED_PROVIDERS:
        entry = PROVIDERS.get(key)
        if not entry:
            continue
        result.append(
            {
                "id": key,
                "name": entry.get("name", key),
                "base_url": get_provider_base_url(key),
                "docs_url": entry.get("docs_url", ""),
                "key_hint": entry.get("key_hint", ""),
                "has_key": provider_has_key(key),
                "active": key == active,
                "custom": key == "custom",
            }
        )
    return result


def get_default_model() -> str:
    value = os.environ.get("OPENAI_MODEL")
    if value and value.strip():
        return value.strip()
    with _SETTINGS_LOCK:
        stored = _read_settings().get("model")
    models = get_models()
    if models:
        ids = {model["id"] for model in models}
        if isinstance(stored, str) and stored.strip() in ids:
            return stored.strip()
        # Prefer a model whose provider is already configured, so the app is
        # ready to chat out of the box for users who added a key.
        ready = next((m for m in models if m.get("has_key")), None)
        return (ready or models[0])["id"]
    return stored.strip() if isinstance(stored, str) and stored.strip() else ""


def set_default_model(model: str) -> None:
    if model and model.strip():
        value = model.strip()
        _write_settings({"model": value})
        # Keep the active provider in sync with the chosen model's owner so the
        # Connection tab always shows the provider that will actually serve it.
        owner = _provider_for_model(value)
        if owner and owner != "custom":
            set_active_provider(owner)


# Reasoning effort levels offered in the UI for reasoning-capable models.
REASONING_LEVELS: list[dict[str, str]] = [
    {"id": "off", "label": "Off", "hint": "Answer without thinking"},
    {"id": "low", "label": "Low", "hint": "Quick reasoning"},
    {"id": "medium", "label": "Medium", "hint": "Balanced (default)"},
    {"id": "high", "label": "High", "hint": "Deep reasoning"},
]


def get_reasoning_effort() -> str:
    """Resolve the saved reasoning level, normalised to a known id."""
    value = os.environ.get("PIKE_REASONING_EFFORT")
    if not (value and value.strip()):
        with _SETTINGS_LOCK:
            stored = _read_settings().get("reasoning_effort")
        value = stored if isinstance(stored, str) else ""
    value = (value or "medium").strip().lower()
    return value if any(level["id"] == value for level in REASONING_LEVELS) else "medium"


def set_reasoning_effort(effort: str | None) -> None:
    value = (effort or "").strip().lower()
    if any(level["id"] == value for level in REASONING_LEVELS):
        _write_settings({"reasoning_effort": value})


# --------------------------------------------------------------------------- #
#  Workspace (the folder opened for coding)                                   #
# --------------------------------------------------------------------------- #
WORKSPACE_KEY = "workspace"


def get_workspace() -> str:
    """Return the currently opened workspace folder, or an empty string."""
    with _SETTINGS_LOCK:
        stored = _read_settings().get(WORKSPACE_KEY)
    if isinstance(stored, str) and stored.strip() and os.path.isdir(stored.strip()):
        return stored.strip()
    return ""


def set_workspace(path: str | None) -> str:
    """Persist the opened workspace folder (empty clears it)."""
    value = (path or "").strip()
    if value and not os.path.isdir(value):
        raise ValueError("That folder does not exist.")
    _write_settings({WORKSPACE_KEY: value})
    return value


HOST = os.environ.get("PIKE_HOST", "127.0.0.1")
PORT = int(os.environ.get("PIKE_PORT", "8765"))
DEBUG = os.environ.get("PIKE_DEBUG", "false").lower() in ("1", "true", "yes")
BROWSER_ONLY = os.environ.get("PIKE_BROWSER_ONLY", "false").lower() in ("1", "true", "yes")
REQUEST_TIMEOUT = int(os.environ.get("PIKE_TIMEOUT", "120"))

# --- Updates --------------------------------------------------------------- #
# Optional JSON manifest describing the latest release, e.g.
#   {"version": "1.2.0", "url": "https://.../Pike.exe", "notes": "What's new"}
UPDATE_URL = os.environ.get("PIKE_UPDATE_URL", "").strip()
# Where the "Open releases" link points when there is no manifest/download URL.
RELEASES_URL = os.environ.get("PIKE_RELEASES_URL", "").strip()


def get_update_url() -> str:
    """Resolve the update manifest URL (env var or saved settings)."""
    if UPDATE_URL:
        return UPDATE_URL
    with _SETTINGS_LOCK:
        stored = _read_settings().get("update_url")
    return stored.strip() if isinstance(stored, str) else ""


SYSTEM_PROMPT = os.environ.get(
    "PIKE_SYSTEM_PROMPT",
    "You are Pike, a thoughtful, friendly and precise AI assistant. "
    "Give clear, well-structured answers. Use Markdown for formatting and code blocks for code.",
)