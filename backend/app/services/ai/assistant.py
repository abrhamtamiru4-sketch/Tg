"""
AI Content Assistant
====================

Wraps AI providers (OpenAI / Anthropic) for content operations.

Functions:
  - generate_post     — Create a new post from a topic/brief
  - rewrite           — Rewrite existing post in different style
  - summarize         — Shorten long content to Telegram-friendly length
  - expand            — Expand a short draft into full post
  - translate         — Translate to target language (preserves entities)
  - correct_grammar   — Grammar and spelling correction
  - generate_titles   — Multiple title options
  - generate_captions — Media captions
  - generate_hashtags — Relevant hashtags
  - generate_cta      — Call-to-action text
  - generate_buttons  — Inline keyboard button labels
  - classify          — Content category classification
  - convert_article   — Long article → Telegram post
  - generate_variants — Multiple A/B variants

Rules:
  • Human approval mode is ON by default.
  • AI never publishes automatically unless FEATURE_AI_AUTO is enabled.
  • All AI output is tagged as [AI_GENERATED] in metadata.
  • Prompt injection from external content is sanitised before submission.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from app.core.config import settings
from app.core.exceptions import AIError, AIProviderNotConfiguredError, FeatureDisabledError
from app.core.feature_flags import is_enabled
from app.core.logging_config import get_logger

log = get_logger(__name__)

AIProvider = Literal["openai", "anthropic"]

# Supported languages for translation
SUPPORTED_LANGUAGES: dict[str, str] = {
    "en": "English",
    "am": "Amharic",
    "ar": "Arabic",
    "fr": "French",
    "es": "Spanish",
    "pt": "Portuguese",
    "de": "German",
    "it": "Italian",
    "tr": "Turkish",
    "hi": "Hindi",
    "zh": "Chinese (Simplified)",
    "ja": "Japanese",
    "ko": "Korean",
    "so": "Somali",
    "sw": "Swahili",
    "ti": "Tigrinya",
}


@dataclass
class AIResult:
    content: str
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    needs_human_approval: bool = True  # Always True unless admin disables
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {"ai_generated": True}


class AIAssistant:
    """
    Provider-agnostic AI content assistant.

    Automatically selects the configured provider.
    All calls are async and raise AIError on failure.
    """

    SYSTEM_PROMPT = """You are a professional Telegram content creator assistant.
Your job is to help create engaging, well-formatted Telegram posts.

RULES:
- Use Telegram-compatible HTML formatting: <b>bold</b>, <i>italic</i>, <u>underline</u>,
  <code>code</code>, <s>strikethrough</s>, <a href="url">link</a>
- Keep posts concise and engaging
- Preserve any links, mentions, and hashtags
- Never include markdown (*, _, #) — use HTML only
- For Ethiopian/Amharic content, be culturally appropriate
- Never invent statistics or facts
- Return ONLY the requested content, no preamble or explanation"""

    def __init__(self) -> None:
        if not is_enabled("AI"):
            raise FeatureDisabledError("AI")
        if settings.ai_provider == "none":
            raise AIProviderNotConfiguredError()

    async def generate_post(
        self,
        topic: str,
        style: str = "informative",
        language: str = "en",
        max_chars: int = 1000,
    ) -> AIResult:
        prompt = (
            f"Write a Telegram channel post about: {topic}\n"
            f"Style: {style}\n"
            f"Language: {SUPPORTED_LANGUAGES.get(language, language)}\n"
            f"Maximum length: {max_chars} characters\n"
            f"Use Telegram HTML formatting."
        )
        return await self._call(prompt)

    async def rewrite(
        self,
        text: str,
        instruction: str = "Make it more engaging",
    ) -> AIResult:
        prompt = (
            f"Rewrite the following Telegram post. {instruction}\n\n"
            f"Original post:\n{self._sanitize(text)}\n\n"
            f"Rewritten post (HTML formatted):"
        )
        return await self._call(prompt)

    async def summarize(self, text: str, max_chars: int = 500) -> AIResult:
        prompt = (
            f"Summarize the following content as a Telegram post of maximum {max_chars} characters. "
            f"Preserve key information and use HTML formatting.\n\n"
            f"Content:\n{self._sanitize(text)}"
        )
        return await self._call(prompt)

    async def expand(self, draft: str, target_chars: int = 800) -> AIResult:
        prompt = (
            f"Expand this draft into a full Telegram post of approximately {target_chars} characters. "
            f"Add context, examples, and engaging language. Use HTML formatting.\n\n"
            f"Draft:\n{self._sanitize(draft)}"
        )
        return await self._call(prompt)

    async def translate(
        self,
        text: str,
        target_language: str,
        preserve_entities: bool = True,
    ) -> AIResult:
        lang_name = SUPPORTED_LANGUAGES.get(target_language, target_language)
        entity_note = (
            "Preserve all HTML tags, @mentions, #hashtags, and URLs unchanged. "
            if preserve_entities else ""
        )
        prompt = (
            f"Translate the following Telegram post to {lang_name}. "
            f"{entity_note}"
            f"Keep HTML formatting. Return ONLY the translation.\n\n"
            f"Text:\n{self._sanitize(text)}"
        )
        return await self._call(prompt)

    async def bilingual(self, text: str, language_a: str, language_b: str) -> AIResult:
        lang_a = SUPPORTED_LANGUAGES.get(language_a, language_a)
        lang_b = SUPPORTED_LANGUAGES.get(language_b, language_b)
        prompt = (
            f"Create a bilingual Telegram post with this content in both {lang_a} and {lang_b}.\n"
            f"Format: {lang_a} version, then a divider line (────────), then {lang_b} version.\n"
            f"Use HTML formatting. Preserve links and mentions.\n\n"
            f"Content:\n{self._sanitize(text)}"
        )
        return await self._call(prompt)

    async def correct_grammar(self, text: str) -> AIResult:
        prompt = (
            f"Correct any grammar, spelling, and punctuation errors in this Telegram post. "
            f"Preserve HTML formatting, links, mentions, and hashtags. "
            f"Return ONLY the corrected text.\n\n"
            f"Text:\n{self._sanitize(text)}"
        )
        return await self._call(prompt)

    async def generate_titles(self, topic: str, count: int = 5) -> list[str]:
        prompt = (
            f"Generate {count} compelling Telegram post titles for: {topic}\n"
            f"Return as a JSON array of strings. No other text."
        )
        result = await self._call(prompt)
        try:
            return json.loads(result.content)
        except json.JSONDecodeError:
            return [line.strip("- ").strip() for line in result.content.split("\n") if line.strip()]

    async def generate_captions(self, image_description: str, count: int = 3) -> list[str]:
        prompt = (
            f"Write {count} engaging Telegram image captions for: {image_description}\n"
            f"Each caption should be 1-3 sentences. Use HTML formatting where appropriate.\n"
            f"Return as a JSON array of strings."
        )
        result = await self._call(prompt)
        try:
            return json.loads(result.content)
        except json.JSONDecodeError:
            return [result.content]

    async def generate_hashtags(self, text: str, count: int = 5) -> list[str]:
        prompt = (
            f"Generate {count} relevant Telegram hashtags for this content. "
            f"Return as a JSON array of strings with # prefix. No other text.\n\n"
            f"Content: {self._sanitize(text[:500])}"
        )
        result = await self._call(prompt)
        try:
            tags = json.loads(result.content)
            return [t if t.startswith("#") else f"#{t}" for t in tags]
        except json.JSONDecodeError:
            return [w for w in result.content.split() if w.startswith("#")]

    async def generate_cta(self, post_text: str, action: str = "read more") -> AIResult:
        prompt = (
            f"Write a concise call-to-action for a Telegram post that encourages users to '{action}'. "
            f"Maximum 80 characters. Use HTML formatting.\n\n"
            f"Post context: {self._sanitize(post_text[:300])}"
        )
        return await self._call(prompt)

    async def generate_button_labels(self, context: str, count: int = 3) -> list[dict]:
        prompt = (
            f"Generate {count} inline button labels for a Telegram post about: {context}\n"
            f"Return as JSON array: [{{'text': '🔥 Label', 'type': 'url'}}]\n"
            f"Types: url, callback. Use emojis. No other text."
        )
        result = await self._call(prompt)
        try:
            return json.loads(result.content)
        except json.JSONDecodeError:
            return [{"text": "Read More", "type": "url"}]

    async def classify(self, text: str) -> dict[str, Any]:
        prompt = (
            f"Classify this Telegram post. Return JSON with keys:\n"
            f"  category (string), subcategory (string), sentiment (positive/neutral/negative),\n"
            f"  topics (array of strings), is_appropriate (boolean)\n"
            f"No other text.\n\nPost: {self._sanitize(text[:1000])}"
        )
        result = await self._call(prompt)
        try:
            return json.loads(result.content)
        except json.JSONDecodeError:
            return {"category": "unknown", "is_appropriate": True}

    async def convert_article(self, article_text: str, max_chars: int = 1200) -> AIResult:
        prompt = (
            f"Convert this article into an engaging Telegram channel post of maximum {max_chars} characters. "
            f"Extract the key points, add relevant emojis, and use HTML formatting. "
            f"End with a clear CTA.\n\n"
            f"Article:\n{self._sanitize(article_text[:4000])}"
        )
        return await self._call(prompt)

    async def generate_variants(self, text: str, count: int = 3) -> list[AIResult]:
        """Generate multiple A/B test variants of a post."""
        styles = ["concise and punchy", "detailed and informative", "question-led and engaging"]
        results = []
        for i, style in enumerate(styles[:count]):
            prompt = (
                f"Rewrite this Telegram post in a {style} style. "
                f"Keep the same core message. Use HTML formatting. "
                f"Return ONLY the rewritten post.\n\nOriginal:\n{self._sanitize(text)}"
            )
            try:
                result = await self._call(prompt)
                result.metadata["variant"] = chr(65 + i)  # A, B, C
                results.append(result)
            except AIError:
                pass
        return results

    # ── Provider routing ──────────────────────────────────────

    async def _call(self, prompt: str) -> AIResult:
        if settings.ai_provider == "openai":
            return await self._call_openai(prompt)
        elif settings.ai_provider == "anthropic":
            return await self._call_anthropic(prompt)
        else:
            raise AIProviderNotConfiguredError()

    async def _call_openai(self, prompt: str) -> AIResult:
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.openai_api_key)
            response = await client.chat.completions.create(
                model=settings.ai_model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=settings.ai_max_tokens,
                temperature=0.7,
            )
            choice = response.choices[0]
            return AIResult(
                content=choice.message.content or "",
                provider="openai",
                model=settings.ai_model,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
            )
        except Exception as exc:
            log.error("openai_error", error=str(exc))
            raise AIError(f"OpenAI error: {exc}") from exc

    async def _call_anthropic(self, prompt: str) -> AIResult:
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            response = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=settings.ai_max_tokens,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return AIResult(
                content=response.content[0].text,
                provider="anthropic",
                model="claude-sonnet-4-6",
                prompt_tokens=response.usage.input_tokens,
                completion_tokens=response.usage.output_tokens,
            )
        except Exception as exc:
            log.error("anthropic_error", error=str(exc))
            raise AIError(f"Anthropic error: {exc}") from exc

    @staticmethod
    def _sanitize(text: str) -> str:
        """
        Remove potential prompt injection from external content.
        Never allow imported text to override system instructions.
        """
        dangerous_patterns = [
            "ignore previous instructions",
            "system prompt",
            "you are now",
            "disregard",
            "forget your",
            "new instructions",
        ]
        lower = text.lower()
        for pattern in dangerous_patterns:
            if pattern in lower:
                # Wrap in a safety boundary
                return f"[IMPORTED CONTENT BEGINS]\n{text}\n[IMPORTED CONTENT ENDS]"
        return text


# Module-level factory — returns None if AI is disabled
def get_ai_assistant() -> AIAssistant | None:
    if not is_enabled("AI") or settings.ai_provider == "none":
        return None
    try:
        return AIAssistant()
    except Exception:
        return None
