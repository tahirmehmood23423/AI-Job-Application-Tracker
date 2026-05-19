"""
LLM-powered structured extraction.

This is where text becomes structured data. The flow is:

  1. Build a precise system prompt that explains the schema and the rules
     (especially "never invent information").
  2. Send the resume text to the LLM.
  3. Parse the JSON response.
  4. Validate against LLMExtractionResult (Pydantic).
  5. On validation failure, retry up to LLM_MAX_RETRIES with a corrective
     follow-up message.

We support both Anthropic and OpenAI behind a tiny abstract interface so the
caller never needs to know which provider is in use. Anthropic is the
recommended default — Claude Haiku 4.5 is fast, cheap, and accurate for this
task.

IMPORTANT: We use the providers' "force JSON" features (tool use for
Anthropic, response_format=json_object for OpenAI). This dramatically reduces
malformed-JSON errors.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from pydantic import ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import Settings, get_settings
from app.core.exceptions import LLMConfigurationError, LLMExtractionError
from app.models.resume import LLMExtractionResult
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ---------- Prompt ----------

SYSTEM_PROMPT = """\
You are a resume parsing assistant. You convert raw resume text into structured JSON.

CRITICAL RULES — these are absolute, no exceptions:

1. NEVER invent information. If a field is not clearly present in the resume, leave it null or empty. Inventing dates, titles, companies, or skills causes real harm to job seekers.

2. Preserve original wording in responsibilities and project descriptions. Do not paraphrase or "improve" the language — the user will do their own editing later.

3. Dates: normalize to YYYY-MM where possible (e.g. "Jan 2023" -> "2023-01"). For currently-held positions, use "Present" as end_date and set is_current=true. If only a year is given, use YYYY-01 as a placeholder and DO NOT invent a month.

4. Skills bucketing:
   - technical: programming languages, frameworks, libraries (Python, React, PyTorch)
   - tools: software, platforms, services (Docker, AWS, Figma, Jira)
   - soft: communication, leadership, teamwork, problem-solving
   - languages: spoken/written human languages (English, Spanish, Urdu)
   Put each skill in EXACTLY ONE bucket. When ambiguous, prefer "technical" for anything code-related.

5. Experience entries: extract every job, including internships. For each, capture company, title, dates, location (if given), each bullet point as a separate "responsibilities" entry, and any technologies mentioned in that role's description.

6. If the resume has a "Summary", "Profile", or "Objective" section at the top, copy it verbatim into the "summary" field.

7. Output MUST be valid JSON matching the schema. Do not include any text outside the JSON object. Do not wrap the JSON in markdown code fences.

8. If you find conflicting information (e.g. two different emails), pick the one that appears first.
"""


USER_PROMPT_TEMPLATE = """\
Parse the following resume into the required JSON schema.

REMEMBER: Never invent information. Leave fields null/empty if not present.

RESUME TEXT:
\"\"\"
{resume_text}
\"\"\"

Return ONLY the JSON object. No prose, no markdown fences.
"""


# ---------- Provider abstraction ----------


class LLMProvider(ABC):
    """Minimal interface every provider must implement."""

    @abstractmethod
    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
        """Return the LLM's response as a raw JSON string."""
        ...


class AnthropicProvider(LLMProvider):
    """Claude provider using the official `anthropic` SDK."""

    def __init__(self, settings: Settings):
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise LLMConfigurationError("`anthropic` package not installed") from e

        if not settings.anthropic_api_key:
            raise LLMConfigurationError("ANTHROPIC_API_KEY is not set")

        self.client = Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.llm_timeout_seconds,
        )
        self.model = settings.anthropic_model

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
        # We use Anthropic's tool-use feature to force structured output.
        # The "tool" is a fake function whose input schema is our Pydantic schema.
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            tools=[
                {
                    "name": "submit_parsed_resume",
                    "description": "Submit the parsed resume as structured data.",
                    "input_schema": schema,
                }
            ],
            tool_choice={"type": "tool", "name": "submit_parsed_resume"},
            messages=[{"role": "user", "content": user}],
        )

        # Find the tool_use block in the response
        for block in response.content:
            if block.type == "tool_use" and block.name == "submit_parsed_resume":
                return json.dumps(block.input)

        raise LLMExtractionError("Anthropic response did not contain expected tool_use block")


class OpenAIProvider(LLMProvider):
    """OpenAI provider using response_format=json_object."""

    def __init__(self, settings: Settings):
        try:
            from openai import OpenAI
        except ImportError as e:
            raise LLMConfigurationError("`openai` package not installed") from e

        if not settings.openai_api_key:
            raise LLMConfigurationError("OPENAI_API_KEY is not set")

        self.client = OpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.llm_timeout_seconds,
        )
        self.model = settings.openai_model

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
        # Note: we pass the schema by reference in the system prompt (OpenAI
        # function calling could be used, but response_format=json_object is
        # simpler and sufficient for this task).
        full_system = (
            f"{system}\n\nThe JSON must match this schema:\n{json.dumps(schema, indent=2)}"
        )
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=4096,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": full_system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""


class GeminiProvider(LLMProvider):
    """
    Google Gemini provider.

    We use a prompt-based JSON approach instead of Gemini's response_schema
    because Gemini's structured-output schema is based on OpenAPI 3.0 and
    rejects many JSON Schema features Pydantic emits (anyOf, $ref, etc.).
    Rather than fighting the schema translation, we ask Gemini to return
    JSON via response_mime_type and validate the output ourselves with
    Pydantic on our side. This is more reliable in production.
    """

    def __init__(self, settings: Settings):
        try:
            import google.generativeai as genai
        except ImportError as e:
            raise LLMConfigurationError("`google-generativeai` package not installed") from e

        if not settings.gemini_api_key:
            raise LLMConfigurationError("GEMINI_API_KEY is not set")

        genai.configure(api_key=settings.gemini_api_key)
        self._genai = genai
        # Google's SDK wants model names prefixed with "models/".
        # Accept either form in the env var to be user-friendly.
        model = settings.gemini_model
        self.model_name = model if model.startswith("models/") else f"models/{model}"
        self.timeout = settings.llm_timeout_seconds

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
        # We include the schema directly in the prompt as guidance.
        # Pydantic validates the response on our side after the call.
        full_system = (
            f"{system}\n\n"
            f"Return JSON that matches this structure:\n"
            f"{json.dumps(schema, indent=2)}\n\n"
            f"CRITICAL: Output ONLY the JSON object, no markdown fences, no prose."
        )

        model = self._genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=full_system,
            generation_config={
                "response_mime_type": "application/json",
                "max_output_tokens": 8192,
                "temperature": 0.1,
            },
        )

        response = model.generate_content(
            user,
            request_options={"timeout": self.timeout},
        )
        return response.text or ""

    @staticmethod
    def _clean_schema_for_gemini(schema: dict[str, Any]) -> dict[str, Any]:
        """
        Gemini's response_schema doesn't accept all JSON Schema features
        Pydantic emits ($defs, $ref, title, additionalProperties, etc.).
        We resolve $refs inline and strip unsupported keys.
        """
        # First, resolve all $refs by inlining the definitions
        defs = schema.get("$defs", {})

        def resolve(node: Any) -> Any:
            if isinstance(node, dict):
                # If this node is a $ref, replace it with the referenced def
                if "$ref" in node:
                    ref_path = node["$ref"]
                    # e.g. "#/$defs/PersonalInfo" -> "PersonalInfo"
                    name = ref_path.split("/")[-1]
                    if name in defs:
                        return resolve(defs[name])
                    return {}
                # Otherwise, recurse into each value
                cleaned = {}
                for k, v in node.items():
                    # Drop unsupported keys
                    if k in {"$defs", "title", "additionalProperties", "default"}:
                        continue
                    cleaned[k] = resolve(v)
                return cleaned
            if isinstance(node, list):
                return [resolve(item) for item in node]
            return node

        return resolve(schema)


# ---------- The main extractor ----------


class LLMExtractor:
    """Coordinates LLM calls to produce a validated LLMExtractionResult."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.provider = self._build_provider(self.settings)
        # Cache the JSON schema once at init
        self._schema = LLMExtractionResult.model_json_schema()

    def _build_provider(self, settings: Settings) -> LLMProvider:
        if settings.llm_provider == "anthropic":
            return AnthropicProvider(settings)
        if settings.llm_provider == "openai":
            return OpenAIProvider(settings)
        if settings.llm_provider == "gemini":
            return GeminiProvider(settings)
        raise LLMConfigurationError(f"Unknown LLM_PROVIDER: {settings.llm_provider}")

    def extract(self, resume_text: str) -> LLMExtractionResult:
        """
        Send the resume text to the LLM and return a validated result.

        Raises:
            LLMExtractionError: After all retries are exhausted.
        """
        # Truncate if the text is unreasonably long (a 50-page CV is suspicious;
        # we cap the prompt to keep cost bounded).
        text = resume_text[: self.settings.max_text_length]
        if len(resume_text) > self.settings.max_text_length:
            logger.warning(
                "Resume text truncated for LLM",
                extra={"original": len(resume_text), "truncated": len(text)},
            )

        return self._extract_with_retry(text)

    @retry(
        retry=retry_if_exception_type(LLMExtractionError),
        stop=stop_after_attempt(3),  # Initial attempt + 2 retries
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _extract_with_retry(self, text: str) -> LLMExtractionResult:
        user_prompt = USER_PROMPT_TEMPLATE.format(resume_text=text)
        try:
            raw = self.provider.complete_json(SYSTEM_PROMPT, user_prompt, self._schema)
        except LLMExtractionError:
            raise
        except Exception as e:
            # Network errors, rate limits, etc. — wrap and let tenacity retry.
            logger.exception("LLM provider call failed")
            raise LLMExtractionError(f"LLM call failed: {e}") from e

        return self._parse_and_validate(raw)

    def _parse_and_validate(self, raw_json: str) -> LLMExtractionResult:
        # The LLM sometimes adds whitespace or stray characters around the JSON.
        # Strip leading/trailing markdown fences if present.
        cleaned = raw_json.strip()
        if cleaned.startswith("```"):
            # Remove opening fence
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            # Remove closing fence
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error("LLM returned invalid JSON", extra={"preview": cleaned[:200]})
            raise LLMExtractionError(f"LLM returned invalid JSON: {e}") from e

        try:
            return LLMExtractionResult.model_validate(data)
        except ValidationError as e:
            logger.error("LLM response failed schema validation", extra={"errors": e.errors()})
            raise LLMExtractionError(f"LLM response failed schema validation: {e}") from e
