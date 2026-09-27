"""OpenAI LLM provider using direct async HTTP calls."""

from typing import Any, Dict, Optional
import httpx

from app.core.errors import LLMProviderError
from app.core.logging import logger
from app.services.llm.base import BaseLLMProvider


class OpenAILLMProvider(BaseLLMProvider):
    """Generates completions using OpenAI Chat Completions REST API."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    @staticmethod
    def _is_json_validation_failure(response: "httpx.Response") -> bool:
        """True when the provider rejected the model's own output for not being
        valid JSON, rather than rejecting the request itself.

        Groq signals this as HTTP 400 with code="json_validate_failed" and the
        offending text in `failed_generation`. Falls back to a substring check
        so a provider that words it differently still gets classified as a
        content failure rather than a hard transport error.
        """
        if response.status_code != 400:
            return False
        try:
            code = response.json().get("error", {}).get("code", "")
        except Exception:
            code = ""
        return code == "json_validate_failed" or "json_validate_failed" in response.text

    async def generate(
        self,
        prompt: str,
        context: Optional[str] = None,
        system_prompt: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Call OpenAI chat completion endpoint."""
        if not self.api_key:
            raise LLMProviderError(
                message="LLM_API_KEY is not configured for OpenAI provider",
                code="LLM_CONFIG_ERROR",
            )

        sys_content = system_prompt or "You are the FlyIO AI planning engine."
        messages = [
            {"role": "system", "content": sys_content},
        ]
        if context:
            messages.append({"role": "system", "content": f"Context information:\n{context}"})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )

            if response.status_code != 200:
                # A server-side JSON-mode validation failure is a *content*
                # problem, not a transport one: the request was fine, the model
                # simply emitted malformed JSON (observed in practice: a
                # description value missing its opening quote). LLMService
                # already handles exactly this with a one-shot retry using a
                # corrective system prompt — but that retry only catches
                # (ValidationError, JSONDecodeError, ValueError). Raising
                # LLMProviderError here meant a provider that validates JSON
                # server-side (Groq returns 400 json_validate_failed) bypassed
                # the retry entirely, while a provider that returns the bad text
                # for us to parse locally got retried. Same failure, different
                # outcome purely by where it was detected. Raise it as a parse
                # error so both paths behave the same.
                if self._is_json_validation_failure(response):
                    logger.warning(
                        "LLM provider rejected its own JSON output "
                        f"(status={response.status_code}); treating as a parse failure so the "
                        "standard corrective retry applies.",
                        extra={"event": "openai_llm_json_validate_failed"},
                    )
                    raise ValueError(
                        f"LLM provider returned invalid JSON (HTTP {response.status_code}): {response.text[:500]}"
                    )

                logger.error(
                    f"OpenAI completion request failed: status={response.status_code} body={response.text}",
                    extra={"event": "openai_llm_error"},
                )
                raise LLMProviderError(
                    message=f"OpenAI LLM provider error: HTTP {response.status_code}",
                    details={"response": response.text},
                )

            data = response.json()
            return data["choices"][0]["message"]["content"]

        except httpx.RequestError as exc:
            logger.error(f"Network error during OpenAI completion: {exc}", extra={"event": "openai_llm_network_error"})
            raise LLMProviderError(message=f"Network error connecting to LLM provider: {str(exc)}")
