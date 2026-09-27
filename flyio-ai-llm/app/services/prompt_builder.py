"""Prompt Builder component for formatting Qdrant context and constructing LLM prompts."""

from typing import List, Optional
from app.schemas.search import SearchResultItem


class PromptBuilder:
    """Constructs structured system and user prompts for travel plan generation."""

    # Payload keys that must never be inlined into the prompt:
    #   text/content   - already emitted as "Content:"; repeating it doubled every item
    #   content_html   - the HTML twin of that same text (scraper-sourced points carry
    #                    it); pure tokens, no added meaning for the model
    _PAYLOAD_KEYS_TO_SKIP = frozenset({"text", "content", "content_html"})

    def __init__(self, max_context_results: int = 5, max_context_chars: int = 12000) -> None:
        self.max_context_results = max_context_results
        self.max_context_chars = max_context_chars

    def format_context(
        self,
        search_results: List[SearchResultItem],
        max_results: Optional[int] = None,
        max_chars: Optional[int] = None,
    ) -> str:
        """Formats retrieved vector search items into a clean text block for LLM context.

        Bounded two ways, because a result-count cap alone is not a bound on
        size: each retrieved chunk can be arbitrarily long (scraper chunks run
        to ~1800 chars), so "top 5 results" could still be tens of thousands of
        characters. Measured against real scraped Wikivoyage content, the
        previous version produced ~23k chars / ~5.8k tokens for 5 results and
        the request was rejected outright by the provider for exceeding its
        token limit.

        1. max_results - keep at most N items (existing behavior).
        2. max_chars   - stop adding items once the budget would be exceeded,
                         so one unusually large chunk cannot blow the request.

        Whole items are dropped rather than cut mid-item, so the model never
        receives a truncated sentence presented as fact.
        """
        if not search_results:
            return "No background context available."

        limit = max_results if max_results is not None else self.max_context_results
        budget = max_chars if max_chars is not None else self.max_context_chars
        items_to_format = search_results[:limit]

        formatted_items: List[str] = []
        used_chars = 0

        for idx, item in enumerate(items_to_format, start=1):
            text_snippet = item.text or item.payload.get("text") or item.payload.get("content") or ""
            score_str = f"{item.score:.2f}" if item.score is not None else "N/A"
            title = item.payload.get("title") or item.payload.get("name") or f"Knowledge Item {idx}"

            # Only the metadata that actually helps the model (source_url,
            # section_path, destination, category...), never the bulk content
            # fields it already has above.
            details = {
                key: value
                for key, value in item.payload.items()
                if key not in self._PAYLOAD_KEYS_TO_SKIP and value not in (None, "", {}, [])
            }

            formatted_item = (
                f"[Context Item {idx}] (Relevance Score: {score_str})\n"
                f"Title/Source: {title}\n"
                f"Content: {text_snippet}\n"
                f"Payload Details: {details}"
            )

            # +2 for the "\n\n" join between items.
            projected = used_chars + len(formatted_item) + (2 if formatted_items else 0)
            if formatted_items and projected > budget:
                break
            formatted_items.append(formatted_item)
            used_chars = projected

        context_str = "\n\n".join(formatted_items)

        omitted = len(search_results) - len(formatted_items)
        if omitted > 0:
            context_str += (
                f"\n\n[Note: Context truncated to the {len(formatted_items)} most relevant "
                f"item(s) out of {len(search_results)} total matches from vector database.]"
            )

        return context_str

    def build_system_prompt(self) -> str:
        """Constructs system instructions enforcing structured JSON output for TravelPlan."""
        return (
            "You are the expert FlyIO AI Travel Planning Engine.\n"
            "Your task is to generate a comprehensive, highly structured travel plan based strictly on the user's prompt "
            "and the provided retrieved background context.\n\n"
            "CRITICAL REQUIREMENT: You MUST respond ONLY with a single valid JSON object adhering strictly to the following schema structure. "
            "Do NOT wrap your output in markdown backticks or extra text outside the JSON object.\n\n"
            "Required JSON Schema Structure:\n"
            "{\n"
            '  "title": "<Itinerary Title>",\n'
            '  "summary": "<High-level trip executive summary>",\n'
            '  "destinations": [\n'
            '    {\n'
            '      "name": "<Destination Name>",\n'
            '      "description": "<Overview>",\n'
            '      "recommended_duration_days": <number_of_days>\n'
            "    }\n"
            "  ],\n"
            '  "attractions": [\n'
            '    {\n'
            '      "name": "<Attraction Name>",\n'
            '      "destination": "<Location>",\n'
            '      "category": "<Landmark|Museum|Park|Dining|etc>",\n'
            '      "description": "<Description & tips>",\n'
            '      "estimated_duration_hours": <number_or_null>\n'
            "    }\n"
            "  ],\n"
            '  "hotels": [\n'
            '    {\n'
            '      "name": "<Hotel Name>",\n'
            '      "destination": "<Location>",\n'
            '      "tier": "<Budget|Mid-Range|Luxury>",\n'
            '      "description": "<Property details>",\n'
            '      "estimated_nightly_rate": "<e.g. $200/night>"\n'
            "    }\n"
            "  ],\n"
            '  "daily_schedule": [\n'
            '    {\n'
            '      "day": "1",\n'
            '      "title": "<Day focus>",\n'
            '      "time": {\n'
            '        "8:00 AM": { "activity": "<Activity>" },\n'
            '        "10:30 AM": { "activity": "<Activity>" },\n'
            '        "1:00 PM": { "activity": "<Activity>" },\n'
            '        "7:00 PM": { "activity": "<Activity>" }\n'
            "      }\n"
            "    }\n"
            "  ],\n"
            '  "budget": {\n'
            '    "currency": "USD",\n'
            '    "accommodation_est": "<Est cost>",\n'
            '    "activities_est": "<Est cost>",\n'
            '    "food_dining_est": "<Est cost>",\n'
            '    "total_estimated": "<Total est cost>"\n'
            "  },\n"
            '  "travel_tips": ["<Tip 1>", "<Tip 2>"]\n'
            "}"
        )

    def build_retry_system_prompt(self) -> str:
        """Constructs corrective system prompt when previous LLM attempt fails JSON parsing."""
        return (
            "Your previous response was not valid JSON matching the required schema. "
            "Please return ONLY a valid, raw JSON object matching the requested TravelPlan schema. "
            "Do not include markdown code block tags like ```json or any conversational prefix/suffix."
        )

    def build_user_prompt(self, user_prompt: str, formatted_context: str) -> str:
        """Combines original user prompt with formatted Qdrant context."""
        return (
            f"User Travel Request:\n{user_prompt}\n\n"
            f"Retrieved Knowledge Context:\n{formatted_context}\n\n"
            "Please generate the complete structured travel plan in JSON format based on the request and context above."
        )
