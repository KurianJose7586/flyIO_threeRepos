"""LLM Service orchestrator implementing AI retrieval and structured plan generation."""

import json
import re
from typing import Optional
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.logging import logger
from app.schemas.generate import GenerateRequest, GenerateResponse, TravelPlan
from app.services.embeddings.service import EmbeddingService
from app.services.llm.base import BaseLLMProvider
from app.services.llm.mock_provider import MockLLMProvider
from app.services.llm.openai_provider import OpenAILLMProvider
from app.services.prompt_builder import PromptBuilder
from app.services.qdrant.service import QdrantService
from app.services.tracking_service import TrackingService


class LLMService:
    """Orchestrates LLM, embedding generation, Qdrant retrieval, and plan generation."""

    def __init__(
        self,
        qdrant_service: Optional[QdrantService] = None,
        embedding_service: Optional[EmbeddingService] = None,
        provider: Optional[BaseLLMProvider] = None,
        prompt_builder: Optional[PromptBuilder] = None,
        tracking_service: Optional[TrackingService] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.qdrant_service = qdrant_service or QdrantService(settings=self.settings)
        self.embedding_service = embedding_service or EmbeddingService(settings=self.settings)
        self.provider = provider or self._resolve_provider()
        self.prompt_builder = prompt_builder or PromptBuilder(
            max_context_results=self.settings.PROMPT_CONTEXT_MAX_RESULTS,
            max_context_chars=self.settings.PROMPT_CONTEXT_MAX_CHARS,
        )
        self.tracking_service = tracking_service or TrackingService(settings=self.settings)


    def _resolve_provider(self) -> BaseLLMProvider:
        """Resolve concrete LLM provider instance."""
        provider_name = self.settings.LLM_PROVIDER.lower()
        if provider_name == "openai":
            logger.info("Using OpenAI LLM provider", extra={"event": "llm_provider_init"})
            return OpenAILLMProvider(
                api_key=self.settings.LLM_API_KEY,
                model=self.settings.LLM_MODEL,
            )
        elif provider_name == "groq":
            # Groq's API is OpenAI-compatible (same request/response shape,
            # including response_format={"type": "json_object"} support) — no
            # separate provider class needed, just a different base_url.
            # https://console.groq.com/docs/openai
            logger.info("Using Groq LLM provider (via OpenAI-compatible client)", extra={"event": "llm_provider_init"})
            return OpenAILLMProvider(
                api_key=self.settings.LLM_API_KEY,
                model=self.settings.LLM_MODEL,
                base_url="https://api.groq.com/openai/v1",
            )
        else:
            logger.info("Using Mock LLM provider", extra={"event": "llm_provider_init"})
            return MockLLMProvider()

    def _clean_json_response(self, raw_text: str) -> str:
        """Clean markdown backticks or formatting from raw LLM output."""
        cleaned = raw_text.strip()
        # Remove ```json ... ``` or ``` ... ``` wrapper if present
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        return cleaned.strip()

    def _parse_travel_plan(self, raw_response: str) -> TravelPlan:
        """Parse raw LLM string into TravelPlan model, raising ValueError on failure."""
        cleaned = self._clean_json_response(raw_response)
        return TravelPlan.model_validate_json(cleaned)

    async def process_generate_request(
        self,
        request: GenerateRequest,
        request_id: str,
    ) -> GenerateResponse:
        """Execute the AI retrieval and plan generation workflow:

        1. Vectorize user prompt via EmbeddingService
        2. Search Qdrant vector database
        3. Branch:
           - Data found: Build prompt with context, invoke LLM, parse TravelPlan (with retry fallback)
           - Data missing: Return structured 'data_required' state
        """
        self.tracking_service.log_event(
            "llm_request_started",
            status="started",
            message=f"Processing generate request for prompt: '{request.prompt[:60]}...'",
            metadata=request.metadata,
            request_id=request_id,
        )

        # 1. Embed query
        query_vector = await self.embedding_service.embed_query(request.prompt)

        # 2. Vector search in Qdrant
        self.tracking_service.log_event(
            "qdrant_search_started",
            status="started",
            message=f"Executing vector search in '{self.settings.QDRANT_COLLECTION_NAME}'",
            request_id=request_id,
        )
        search_result = await self.qdrant_service.search(
            query_vector=query_vector,
            collection_name=self.settings.QDRANT_COLLECTION_NAME,
            score_threshold=self.settings.QDRANT_SEARCH_SCORE_THRESHOLD,
        )

        # 3. Formulate response and generate plan if data is found
        if search_result.found:
            self.tracking_service.log_event(
                "qdrant_search_completed",
                status="data_found",
                message=f"Knowledge retrieval succeeded with {len(search_result.results)} match(es)",
                metadata={"matches": len(search_result.results)},
                request_id=request_id,
            )

            # Format context and build prompts
            formatted_context = self.prompt_builder.format_context(
                search_result.results,
                max_results=self.settings.PROMPT_CONTEXT_MAX_RESULTS,
                max_chars=self.settings.PROMPT_CONTEXT_MAX_CHARS,
            )
            system_prompt = self.prompt_builder.build_system_prompt()
            user_prompt = self.prompt_builder.build_user_prompt(request.prompt, formatted_context)

            self.tracking_service.log_event(
                "plan_generation_started",
                status="started",
                message="Starting travel plan generation via LLM provider",
                request_id=request_id,
            )

            plan: Optional[TravelPlan] = None
            try:
                # Attempt 1: Generate completion, then parse it.
                #
                # The generate() call is inside this try on purpose. Providers
                # that validate JSON mode server-side (Groq) reject the model's
                # malformed output at the API boundary, so the failure surfaces
                # from generate() rather than from _parse_travel_plan() — see
                # OpenAILLMProvider._is_json_validation_failure. Leaving the
                # call outside meant that exact failure skipped the retry below
                # and escaped as an unhandled error, purely because of where it
                # was detected.
                raw_response = await self.provider.generate(
                    prompt=user_prompt,
                    context=formatted_context,
                    system_prompt=system_prompt,
                    metadata=request.metadata,
                )
                plan = self._parse_travel_plan(raw_response)
            except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                logger.warning(
                    f"First LLM plan generation attempt failed JSON validation: {exc}. Retrying once...",
                    extra={"event": "plan_generation_retry", "request_id": request_id},
                )
                # Attempt 2: One retry with corrective system prompt
                retry_system_prompt = self.prompt_builder.build_retry_system_prompt()
                try:
                    retry_raw_response = await self.provider.generate(
                        prompt=user_prompt,
                        context=formatted_context,
                        system_prompt=retry_system_prompt,
                        metadata=request.metadata,
                    )
                    plan = self._parse_travel_plan(retry_raw_response)
                except (ValidationError, json.JSONDecodeError, ValueError) as retry_exc:
                    logger.error(
                        f"Retry LLM plan generation also failed JSON validation: {retry_exc}",
                        extra={"event": "plan_generation_failed", "request_id": request_id},
                    )

            if plan is not None:
                self.tracking_service.log_event(
                    "plan_generation_completed",
                    status="completed",
                    message="Travel plan generated successfully",
                    request_id=request_id,
                )
                return GenerateResponse(
                    success=True,
                    request_id=request_id,
                    status="data_found",
                    data_found=True,
                    data_required=False,
                    results=search_result.results,
                    plan=plan,
                    message=f"Relevant data found ({len(search_result.results)} matches). Travel plan generated successfully.",
                    metadata=request.metadata,
                )
            else:
                self.tracking_service.log_event(
                    "plan_generation_failed",
                    status="failed",
                    message="Plan generation failed to produce valid structured output after retry",
                    request_id=request_id,
                )
                return GenerateResponse(
                    success=True,
                    request_id=request_id,
                    status="generation_failed",
                    data_found=True,
                    data_required=False,
                    results=search_result.results,
                    plan=None,
                    message="Plan generation failed to produce valid structured output.",
                    metadata=request.metadata,
                )

        else:
            self.tracking_service.log_event(
                "qdrant_search_completed",
                status="data_required",
                message="Knowledge retrieval: no matching context in Qdrant. Source data required.",
                request_id=request_id,
            )
            return GenerateResponse(
                success=True,
                request_id=request_id,
                status="data_required",
                data_found=False,
                data_required=True,
                results=[],
                plan=None,
                message="Data missing in vector database. Source data extraction / scraping required.",
                metadata=request.metadata,
            )

