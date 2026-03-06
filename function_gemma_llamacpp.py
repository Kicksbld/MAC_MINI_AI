"""
Demo complet : appeler FunctionGemma (quantisé GGUF via llama.cpp) en mode
tool calling, exécuter les fonctions Python correspondantes, et renvoyer la
réponse finale à l'utilisateur.

Prérequis côté serveur
----------------------
1) Builder llama.cpp (ex. Mac M-series : cmake -DGGML_METAL=on).
2) Lancer le serveur OpenAI-compatible, par ex. :
   ./build/bin/server -m models/functiongemma-270m-it-Q4_K_M.gguf \
     --host 127.0.0.1 --port 8080 --ctx-size 4096 --threads 6 --metal

Prérequis côté client
---------------------
pip install "openai>=1.3"

Exemple d'exécution
-------------------
python function_gemma_llamacpp.py "Convertis 42 EUR en USD."
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List

from openai import OpenAI

# Configuration connexion serveur llama.cpp
BASE_URL = os.environ.get("LLAMA_CPP_BASE_URL", "http://127.0.0.1:8080/v1")
API_KEY = os.environ.get("LLAMA_CPP_API_KEY", "devkey")
MODEL_NAME = os.environ.get("LLAMA_CPP_MODEL", "functiongemma-270m-it-Q4_K_M.gguf")


# --- Fonctions Python exposées ---
def convert_currency(amount: float, currency_from: str, currency_to: str) -> Dict[str, Any]:
    """Conversion fictive EUR<->USD pour démonstration."""
    rates = {("EUR", "USD"): 1.08, ("USD", "EUR"): 0.93}
    rate = rates.get((currency_from.upper(), currency_to.upper()))
    if rate is None:
        raise ValueError(f"Aucun taux démo pour {currency_from}->{currency_to}")
    from datetime import timezone
    return {
        "original_amount": amount,
        "original_currency": currency_from.upper(),
        "amount": round(amount * rate, 2),
        "currency": currency_to.upper(),
        "rate_used": rate,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def add_days(start_date: str, days: int) -> Dict[str, Any]:
    """Ajoute des jours à une date ISO (YYYY-MM-DD)."""
    base = datetime.fromisoformat(start_date)
    target = base + timedelta(days=days)
    return {"result_date": target.date().isoformat()}


TOOLS_DECL: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "convert_currency",
            "description": "Convertir un montant entre deux devises.",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number"},
                    "currency_from": {"type": "string"},
                    "currency_to": {"type": "string"},
                },
                "required": ["amount", "currency_from", "currency_to"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_days",
            "description": "Ajouter un nombre de jours à une date YYYY-MM-DD.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string"},
                    "days": {"type": "integer"},
                },
                "required": ["start_date", "days"],
            },
        },
    },
]


FUNC_MAP = {
    "convert_currency": convert_currency,
    "add_days": add_days,
}

# Déclarations simplifiées pour le prompt (format attendu par FunctionGemma)
TOOL_DECLARATIONS_TEXT = [
    {
        "name": "convert_currency",
        "description": "Convert an amount between two currencies.",
        "parameters": {
            "type": "object",
            "properties": {
                "amount": {"type": "number"},
                "currency_from": {"type": "string"},
                "currency_to": {"type": "string"},
            },
            "required": ["amount", "currency_from", "currency_to"],
        },
    },
    {
        "name": "add_days",
        "description": "Add days to a date (YYYY-MM-DD).",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string"},
                "days": {"type": "integer"},
            },
            "required": ["start_date", "days"],
        },
    },
]

# Instruction système pour FunctionGemma (format officiel Google)
SYSTEM_PROMPT = """<start_of_turn>system
You are a helpful assistant. You have access to these functions:

"""

FUNCTION_CALL_INSTRUCTION = """
Example: If user says "Convert 100 USD to EUR", respond with:
{"name": "convert_currency", "parameters": {"amount": 100, "currency_from": "USD", "currency_to": "EUR"}}

Example: If user says "What date is 10 days after 2024-01-15", respond with:
{"name": "add_days", "parameters": {"start_date": "2024-01-15", "days": 10}}

IMPORTANT: Output ONLY the JSON. No text before or after.
<end_of_turn>
<start_of_turn>user
"""


def build_prompt_with_tools(user_prompt: str) -> str:
    """Construit le prompt avec les déclarations de fonctions intégrées."""
    tools_json = json.dumps(TOOL_DECLARATIONS_TEXT, indent=2, ensure_ascii=False)
    return f"{SYSTEM_PROMPT}{tools_json}{FUNCTION_CALL_INSTRUCTION}{user_prompt}<end_of_turn>\n<start_of_turn>model\n"


def parse_function_call(response: str) -> Dict[str, Any] | None:
    """Tente d'extraire un appel de fonction JSON de la réponse."""
    text = response.strip()
    
    # Nettoyer les tokens spéciaux de FunctionGemma
    text = text.replace("<start_function_call>", "").replace("<end_function_call>", "")
    text = text.replace("<end_of_turn>", "").strip()
    
    # Nettoyer les éventuels backticks markdown
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    
    try:
        data = json.loads(text)
        if "name" in data:
            return data
    except json.JSONDecodeError:
        # Chercher un JSON dans le texte
        import re
        match = re.search(r'\{[^{}]*"name"\s*:\s*"[^"]+"\s*,\s*"parameters"\s*:\s*\{[^}]*\}[^}]*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


def run_chat(user_prompt: str) -> str:
    client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

    # Étape 1 : Demander au modèle s'il veut appeler une fonction
    full_prompt = build_prompt_with_tools(user_prompt)
    
    # Utiliser l'endpoint completions au lieu de chat pour plus de contrôle
    resp = client.completions.create(
        model=MODEL_NAME,
        prompt=full_prompt + '{"name": "',  # Forcer le début du JSON
        temperature=0.0,
        max_tokens=100,
        stop=["\n", "<end_of_turn>", "<end_function_call>"],
    )

    raw_response = '{"name": "' + (resp.choices[0].text or "")
    print(f"[DEBUG] Réponse brute du modèle:\n{raw_response}\n")

    # Étape 2 : Parser l'appel de fonction
    func_call = parse_function_call(raw_response)
    
    if func_call is None:
        # Pas d'appel de fonction détecté, retourner la réponse directe
        return raw_response

    name = func_call.get("name", "")
    params = func_call.get("parameters", {})
    print(f"[DEBUG] Fonction détectée: {name}, params: {params}")

    func = FUNC_MAP.get(name)
    if func is None:
        return f"Erreur: fonction '{name}' non disponible."

    # Étape 3 : Exécuter la fonction
    try:
        result = func(**params)
    except Exception as exc:
        return f"Erreur lors de l'exécution de {name}: {exc}"

    print(f"[DEBUG] Résultat de la fonction: {result}")

    
    return f"Résultat: {json.dumps(result, ensure_ascii=False)}"


def main():
    prompt = " ".join(sys.argv[1:]).strip()
    if not prompt:
        prompt = "Convertis 42 EUR en USD et indique le résultat."
    answer = run_chat(prompt)
    print("\nRéponse finale :\n", answer)


if __name__ == "__main__":
    main()
