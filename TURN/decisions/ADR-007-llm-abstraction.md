# ADR-007: LLM Provider Abstraction

**Status:** Decided  
**Date:** 2026-06-04

---

## Context

The LLM landscape changes fast — pricing drops, new models appear, capabilities shift. If OpenAI calls are hardcoded throughout the codebase, switching providers means touching every file. That's a refactor that won't happen until it's painful.

---

## Decision

All AI calls go through a single `LLMClient` interface in `core/llm_client.py`. Provider is selected via `LLM_PROVIDER` environment variable. Different providers can be configured for different tasks.

---

## The Interface

```python
# core/llm_client.py

class LLMClient:
    def __init__(self, provider: str = None):
        self.provider = provider or config.LLM_PROVIDER

    async def vision(self, image_base64: str, system_prompt: str) -> dict:
        """Extract text + ghost risk from screenshot. Returns parsed JSON dict."""
        ...

    async def complete(self, system: str, user: str, json_mode: bool = False) -> str:
        """Generate scripts, regenerate scripts. Returns string (or JSON string)."""
        ...
```

The rest of `core/` only ever calls `LLMClient.vision()` and `LLMClient.complete()`. No provider SDK is imported outside `llm_client.py`.

---

## Provider Implementations

### OpenAI (default)
```python
# vision: gpt-4o with image input
# complete: gpt-4o or gpt-3.5-turbo
# json_mode: response_format={"type": "json_object"}
```
**Strengths:** Reliable, well-documented, strong vision  
**Weaknesses:** Most expensive; US-centric data practices

### Anthropic (Claude)
```python
# vision: claude-3-5-sonnet with image input (base64)
# complete: claude-3-5-sonnet or claude-haiku-3
# Note: Claude has no native json_mode — use prompt instruction instead
```
**Strengths:** Best natural language quality; scripts sound most human; strong at following tone instructions  
**Weaknesses:** No native JSON mode (use prompt engineering); slightly higher latency  
**Best for:** Script generation — Claude produces the most natural-sounding copy

### Google (Gemini)
```python
# vision: gemini-1.5-pro with inline image data
# complete: gemini-1.5-flash (fast + cheap) or gemini-1.5-pro
# json_mode: response_mime_type="application/json"
```
**Strengths:** Cheapest vision option; fast; long context window  
**Weaknesses:** Less consistent on structured outputs than OpenAI  
**Best for:** Vision OCR — cheaper than GPT-4o for the same quality

### DeepSeek
```python
# complete only (no vision model at time of writing)
# API is OpenAI-compatible — swap base_url only
# json_mode: supported
```
**Strengths:** Extremely cheap (~10x cheaper than GPT-4); good reasoning  
**Weaknesses:** No vision; data processed in China (privacy consideration for some users)  
**Best for:** Script regeneration — low-stakes, cost-sensitive task

### MiniMax
```python
# complete: abab6.5s or abab5.5
# API: REST with different format from OpenAI
```
**Strengths:** Cheap; good for Chinese-language users (future)  
**Weaknesses:** Less tested for English nuance; smaller community  
**Best for:** Not recommended for MVP — use DeepSeek instead for cost reduction

---

## Recommended Configuration by Task

| Task | Default Provider | Reason |
|------|-----------------|--------|
| Vision OCR (screenshot analysis) | Gemini 1.5 Pro | Cheapest vision with comparable quality |
| Script generation | Claude Sonnet | Best natural language; scripts sound most human |
| Script regeneration | DeepSeek | Low-stakes, cheapest option |

**Env config for optimized setup:**
```
LLM_VISION_PROVIDER=gemini
LLM_SCRIPT_PROVIDER=anthropic
LLM_REGEN_PROVIDER=deepseek
```

**Env config for simplest setup (MVP start):**
```
LLM_PROVIDER=openai   # all tasks use OpenAI — simplest to start
```

---

## Cost Comparison Per Conversation

| Setup | Vision | Scripts | Regen | Total |
|-------|--------|---------|-------|-------|
| All OpenAI (GPT-4o) | $0.013 | $0.011 | $0.001 | ~$0.025 |
| Optimized (Gemini + Claude + DeepSeek) | $0.004 | $0.008 | $0.0002 | ~$0.012 |
| All DeepSeek (no vision) | N/A | $0.001 | $0.0002 | ~$0.001 |

At $5 revenue per paying conversation, all configurations are profitable. The optimization matters at scale (10k+ conversations/month), not at MVP.

**Start with all-OpenAI for simplicity. Switch providers after real usage data confirms quality.**

---

## How to Add a New Provider

1. Add a new `elif self.provider == 'newprovider':` block in `llm_client.py`
2. Add the API key env var to `config.py`
3. Test with the existing prompt suite
4. No other files change

---

## Why Not Use LangChain or LiteLLM

LangChain adds significant abstraction overhead and changes frequently. LiteLLM is closer to what we need but adds a dependency for something that's 100 lines of code.

TURN only needs two operations: vision and text completion. The abstraction is simple enough to own. A custom `LLMClient` gives full control over retry logic, error handling, and cost logging without a framework getting in the way.

If the provider count grows beyond 5 and the abstraction becomes complex, reconsider LiteLLM at that point.
