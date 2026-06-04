# Plan 9 — Multi-LLM Provider Support

**Builds:** Add Claude, Gemini, DeepSeek to LLMClient — per-task routing via env config  
**Depends on:** Plan 7 complete (MVP validated). Can run in parallel with Plan 8.  
**Time:** ~0.5 day

---

## State Before
`LLMClient` only implements OpenAI. `LLM_VISION_PROVIDER`, `LLM_SCRIPT_PROVIDER`, `LLM_REGEN_PROVIDER` env vars exist in config but are all defaulted to `openai`.

## State After
All four providers work. Default config routes: Gemini for vision (cheaper), Claude for scripts (best copy quality), DeepSeek for regen (cheapest). Can be overridden to all-OpenAI by setting one env var.

---

## All Decisions Already Made — From ADR-007

| Task | Default Provider | Why |
|------|-----------------|-----|
| Vision OCR | Gemini 1.5 Pro | Cheapest vision with comparable quality to GPT-4o |
| Script generation | Claude Sonnet | Best natural language — scripts sound most human |
| Script regeneration | DeepSeek | Cheapest — low-stakes task |

Cost per conversation comparison:
- All OpenAI:   ~$0.025
- Optimized:    ~$0.012
- All DeepSeek: ~$0.001 (no vision — use for text-only path)

Do not switch away from all-OpenAI until you have 20+ conversations of real data to compare quality. The optimized config is the target, not the starting point.

---

## Epic 1 — Add Providers to LLMClient

### Task 9.1 — Update `core/llm_client.py`

Add implementation blocks for each provider. Interface stays identical.

```python
import base64
import json
import asyncio
import config

class LLMClient:
    def __init__(self, provider: str = None):
        self.provider = provider or config.LLM_PROVIDER

    async def vision(self, image_base64: str, system_prompt: str) -> dict:
        if self.provider == "openai":
            return await self._openai_vision(image_base64, system_prompt)
        elif self.provider == "gemini":
            return await self._gemini_vision(image_base64, system_prompt)
        elif self.provider == "anthropic":
            return await self._anthropic_vision(image_base64, system_prompt)
        raise NotImplementedError(f"Vision not supported for provider: {self.provider}")

    async def complete(self, system: str, user: str, json_mode: bool = False) -> str:
        if self.provider == "openai":
            return await self._openai_complete(system, user, json_mode)
        elif self.provider == "anthropic":
            return await self._anthropic_complete(system, user, json_mode)
        elif self.provider == "gemini":
            return await self._gemini_complete(system, user, json_mode)
        elif self.provider == "deepseek":
            return await self._deepseek_complete(system, user, json_mode)
        raise NotImplementedError(f"Complete not supported for provider: {self.provider}")

    # --- OpenAI (already implemented in Plan 0) ---
    # (keep existing _openai_vision and _openai_complete methods)

    # --- Anthropic (Claude) ---

    async def _anthropic_vision(self, image_base64: str, system_prompt: str) -> dict:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        resp = await client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=600,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": [{
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_base64,
                    }
                }]
            }]
        )
        # Claude doesn't have native json_mode — parse the content
        text = resp.content[0].text
        # Strip markdown code blocks if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())

    async def _anthropic_complete(self, system: str, user: str, json_mode: bool = False) -> str:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        
        system_with_json = system
        if json_mode:
            system_with_json += "\n\nIMPORTANT: Return ONLY valid JSON. No markdown, no explanation, just the JSON object."
        
        resp = await client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=500,
            system=system_with_json,
            messages=[{"role": "user", "content": user}]
        )
        text = resp.content[0].text.strip()
        
        if json_mode:
            # Strip any markdown code fences Claude might add despite instructions
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            text = text.strip()
        
        return text

    # --- Google Gemini ---

    async def _gemini_vision(self, image_base64: str, system_prompt: str) -> dict:
        import google.generativeai as genai
        genai.configure(api_key=config.GOOGLE_API_KEY)
        model = genai.GenerativeModel(
            model_name="gemini-1.5-pro",
            generation_config={"response_mime_type": "application/json"}
        )
        import PIL.Image
        import io
        image_data = base64.b64decode(image_base64)
        img = PIL.Image.open(io.BytesIO(image_data))
        
        resp = await asyncio.to_thread(  # Gemini SDK is sync — run in thread
            model.generate_content,
            [system_prompt, img]
        )
        return json.loads(resp.text)

    async def _gemini_complete(self, system: str, user: str, json_mode: bool = False) -> str:
        import google.generativeai as genai
        genai.configure(api_key=config.GOOGLE_API_KEY)
        
        generation_config = {}
        if json_mode:
            generation_config["response_mime_type"] = "application/json"
        
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",  # flash = cheaper + faster for text
            system_instruction=system,
            generation_config=generation_config
        )
        resp = await asyncio.to_thread(model.generate_content, user)
        return resp.text

    # --- DeepSeek ---
    # DeepSeek API is OpenAI-compatible — just different base_url and model name

    async def _deepseek_complete(self, system: str, user: str, json_mode: bool = False) -> str:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com"
        )
        kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
        resp = await client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            max_tokens=500,
            **kwargs
        )
        return resp.choices[0].message.content
```

---

## Epic 2 — Update Module-Level Singletons

### Task 9.2 — Bottom of `core/llm_client.py`

```python
# These are the three clients used throughout the codebase.
# To change providers: update LLM_VISION_PROVIDER, LLM_SCRIPT_PROVIDER, LLM_REGEN_PROVIDER in .env
# To use all-OpenAI (simplest): set LLM_PROVIDER=openai and leave the others unset.

vision_client = LLMClient(provider=config.LLM_VISION_PROVIDER)
script_client  = LLMClient(provider=config.LLM_SCRIPT_PROVIDER)
regen_client   = LLMClient(provider=config.LLM_REGEN_PROVIDER)
```

---

## Task 9.3 — Recommended `.env` configurations

**Simplest (all OpenAI — start here):**
```
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

**Optimized (after quality validation):**
```
LLM_VISION_PROVIDER=gemini
LLM_SCRIPT_PROVIDER=anthropic
LLM_REGEN_PROVIDER=deepseek
OPENAI_API_KEY=sk-...        ← keep for fallback
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=AIza...
DEEPSEEK_API_KEY=sk-...
```

**All Claude (if OpenAI goes down or pricing shifts):**
```
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Task 9.4 — How to validate quality before switching

Run 10 real conversation screenshots through both OpenAI and the new provider. Compare:
1. Is the ghost risk score similar? (within ±10 points)
2. Do the scripts sound natural? (read them out loud)
3. Is the JSON output clean? (no markdown fences, valid JSON)
4. Is latency acceptable? (<5s for vision, <3s for scripts)

Only switch if quality is comparable. Claude for scripts is almost certainly better — switch that first.

---

## Acceptance Criteria — Plan 9 Complete When:

- [ ] Setting `LLM_PROVIDER=anthropic` → scripts generated via Claude API
- [ ] Setting `LLM_VISION_PROVIDER=gemini` → vision OCR via Gemini
- [ ] Setting `LLM_REGEN_PROVIDER=deepseek` → regeneration via DeepSeek
- [ ] `LLMClient("invalid_provider").complete(...)` raises `NotImplementedError` with clear message
- [ ] Missing API key for configured provider → error on startup or clear error on first call
- [ ] All existing Plan 0-7 acceptance criteria still pass with all-OpenAI config
