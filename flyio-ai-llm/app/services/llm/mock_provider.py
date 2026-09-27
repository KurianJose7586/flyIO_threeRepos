"""Mock LLM provider for testing and offline development."""

import json
from typing import Any, Dict, Optional
from app.services.llm.base import BaseLLMProvider


class MockLLMProvider(BaseLLMProvider):
    """Returns simulated LLM responses without external API dependencies."""

    def __init__(
        self,
        custom_response: Optional[str] = None,
        fail_first_n_times: int = 0,
    ) -> None:
        self.custom_response = custom_response
        self.fail_first_n_times = fail_first_n_times
        self._call_count = 0

    async def generate(
        self,
        prompt: str,
        context: Optional[str] = None,
        system_prompt: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Return deterministic simulated output based on prompt."""
        self._call_count += 1

        if self._call_count <= self.fail_first_n_times or "INVALID_JSON_TEST" in prompt:
            return "This is not valid JSON output from simulated LLM failure."

        if self.custom_response:
            return self.custom_response

        # If system prompt mentions JSON or schema, return valid TravelPlan JSON
        topic = "Paris" if "Paris" in prompt else prompt.replace("User Travel Request:\n", "").split("\n")[0][:30]
        mock_plan = {
            "title": f"Simulated Travel Plan for {topic}",
            "summary": f"Custom travel itinerary generated using retrieved context ({len(context) if context else 0} chars).",
            "destinations": [
                {
                    "name": "Paris, France",
                    "description": "Capital of France known for art, fashion, gastronomy, and culture.",
                    "recommended_duration_days": 3,
                }
            ],
            "attractions": [
                {
                    "name": "Eiffel Tower",
                    "destination": "Paris, France",
                    "category": "Landmark",
                    "description": "Iconic wrought-iron lattice tower on the Champ de Mars.",
                    "estimated_duration_hours": 2.5,
                },
                {
                    "name": "Louvre Museum",
                    "destination": "Paris, France",
                    "category": "Museum",
                    "description": "World's largest art museum housing Mona Lisa.",
                    "estimated_duration_hours": 4.0,
                },
            ],
            "hotels": [
                {
                    "name": "Hôtel Plaza Athénée",
                    "destination": "Paris, France",
                    "tier": "Luxury",
                    "description": "Historic 5-star hotel near Avenue Montaigne.",
                    "estimated_nightly_rate": "$450/night",
                }
            ],
            "daily_schedule": [
                {
                    "day": "1",
                    "title": "Arrival & City Overview",
                    "time": {
                        "8:00 AM": {"activity": "Morning walk and breakfast at a local cafe."},
                        "11:00 AM": {"activity": "Check in at hotel."},
                        "2:00 PM": {"activity": "Visit the Eiffel Tower and Champ de Mars gardens."},
                        "7:30 PM": {"activity": "Dinner cruise along the Seine River."},
                    },
                },
                {
                    "day": "2",
                    "title": "Art & History",
                    "time": {
                        "9:00 AM": {"activity": "Guided tour of the Louvre Museum."},
                        "1:30 PM": {"activity": "Stroll through Tuileries Garden and Place de la Concorde."},
                        "7:00 PM": {"activity": "Classic French cuisine in Saint-Germain-des-Prés."},
                    },
                },
            ],
            "budget": {
                "currency": "USD",
                "accommodation_est": "$900",
                "activities_est": "$150",
                "food_dining_est": "$300",
                "total_estimated": "$1,350",
            },
            "travel_tips": [
                "Purchase museum passes in advance to skip long lines.",
                "Use the Paris Metro for fast transit across the city.",
            ],
        }

        return json.dumps(mock_plan)
