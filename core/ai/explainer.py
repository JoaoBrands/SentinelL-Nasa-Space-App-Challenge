"""Layer 2 - Explainable AI using local Ollama (Qwen 2.5) with RAG fallback."""
import json
import ollama
from core.config import DATA_DIR, OLLAMA_REQUEST_TIMEOUT_SECONDS

# Load the fallback (plan B)
def load_rag_cache():
    try:
        with open(DATA_DIR / "rag_cache.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

RAG_CACHE = load_rag_cache()
OLLAMA_CLIENT = ollama.Client(timeout=OLLAMA_REQUEST_TIMEOUT_SECONDS)

SYSTEM_PROMPT = """
You are the clinical explanation module for the Sentinel prototype.
Your only function is to explain an already classified physiological alert.
Never change the risk state. Never make diagnoses.
Base the explanation strictly on the NASA context provided.
Write every response in English.

Use exactly this format:
Explanation: [1 to 2 sentences explaining the mechanism based on the context]
Action: [1 sentence with a recommended action, without mandatory force]
Sources: [source IDs]
"""

def generate_explanation(alert: dict) -> dict:
    rule_id = alert.get("rule_id", "unknown")

    # 1. Try the live AI (Ollama)
    try:
        # Build the context using the cache as the knowledge base (RAG)
        context = RAG_CACHE.get(rule_id, {})
        context_str = json.dumps(context, ensure_ascii=False) if context else "No specific context available."

        user_prompt = f"""
        [ALERT DATA]
        Rule ID: {rule_id}
        Status: {alert['status']}
        Finding: {alert['text']}
        Metrics: {alert.get('evidence', [])}

        [NASA CONTEXT]
        {context_str}
        """

        response = OLLAMA_CLIENT.chat(model='qwen2.5:7b', messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': user_prompt},
        ], options={'temperature': 0.1})

        content = response['message']['content']

        lines = content.split('\n')
        explanation = next((l.replace('Explanation:', '').strip() for l in lines if l.startswith('Explanation:')), content)
        action = next((l.replace('Action:', '').strip() for l in lines if l.startswith('Action:')), "Follow the standard protocol.")
        citations = next((l.replace('Sources:', '').strip() for l in lines if l.startswith('Sources:')), "")

        return {
            "ai_explanation": explanation,
            "ai_action": action,
            "ai_citations": [citations] if citations else [],
            "ai_source": "LIVE (Ollama Qwen 2.5)"
        }

    except Exception as e:
        print(f"[OLLAMA ERROR] {e}. Using precomputed explanation.")
        fallback = RAG_CACHE.get(rule_id, {})
        return {
            "ai_explanation": fallback.get("explanation", "No explanation available."),
            "ai_action": fallback.get("action", "Monitor carefully."),
            "ai_citations": fallback.get("citations", []),
            "ai_source": "PRECOMPUTED"
        }