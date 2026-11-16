import unittest
from unittest.mock import patch

import httpx
from core.ai.explainer import RAG_CACHE, OLLAMA_CLIENT, generate_explanation


class EnglishExplainerTests(unittest.TestCase):
    def test_parses_english_explanation_action_and_source_fields(self):
        response = {
            "message": {
                "content": (
                    "Explanation: Reduced ventilation can allow local CO₂ to accumulate.\n"
                    "Action: Check local ventilation.\n"
                    "Sources: NASA-NTRS-20180000936"
                )
            }
        }
        with patch.object(OLLAMA_CLIENT, "chat", return_value=response):
            result = generate_explanation({
                "rule_id": "co2_pocket_inference",
                "status": "OBSERVE",
                "text": "Simulated elevated local CO₂ risk.",
                "evidence": ["ana_local_co2"],
            })

        self.assertEqual(result["ai_explanation"], "Reduced ventilation can allow local CO₂ to accumulate.")
        self.assertEqual(result["ai_action"], "Check local ventilation.")
        self.assertEqual(result["ai_citations"], ["NASA-NTRS-20180000936"])
        self.assertEqual(result["ai_source"], "LIVE (Ollama Qwen 2.5)")

    def test_ollama_timeout_falls_back_to_cached_explanation(self):
        with patch.object(OLLAMA_CLIENT, "chat", side_effect=httpx.ReadTimeout("request timed out")):
            result = generate_explanation({
                "rule_id": "co2_pocket_inference",
                "status": "OBSERVE",
                "text": "Simulated elevated local CO₂ risk.",
                "evidence": ["ana_local_co2"],
            })

        fallback = RAG_CACHE["co2_pocket_inference"]
        self.assertEqual(result["ai_explanation"], fallback["explanation"])
        self.assertEqual(result["ai_action"], fallback["action"])
        self.assertEqual(result["ai_citations"], fallback["citations"])
        self.assertEqual(result["ai_source"], "PRECOMPUTED")


if __name__ == "__main__":
    unittest.main()