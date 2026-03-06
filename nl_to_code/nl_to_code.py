#!/usr/bin/env python3
import os
import json
import sys
import requests

BASE_URL = os.getenv("LLAMA_BASE_URL", "http://localhost:8080")
API_KEY = os.getenv("LLAMA_API_KEY", "sk-no-key")  # souvent ignoré par llama.cpp
MODEL = os.getenv("LLAMA_MODEL", "gpt-3.5-turbo")  # llama.cpp ignore parfois / ou accepte un nom

CHAT_URL = f"{BASE_URL.rstrip('/')}/v1/chat/completions"


def chat_once(system:str, prompt: str, stream: bool = False) -> str:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "stream": stream,
    }

    if not stream:
        r = requests.post(CHAT_URL, headers=headers, json=payload, timeout=120)
        r.raise_for_status()
        data = json.loads(r.content.decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        return content

    # Streaming (SSE): on lit ligne par ligne
    with requests.post(CHAT_URL, headers=headers, json=payload, stream=True, timeout=120) as r:
        r.raise_for_status()
        r.encoding = "utf-8"
        out = []
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            # Les serveurs SSE préfixent souvent par "data: "
            if line.startswith("data: "):
                line = line[len("data: "):]

            if line.strip() == "[DONE]":
                break

            try:
                event = json.loads(line)
                delta = event["choices"][0].get("delta", {}).get("content")
                if delta:
                    out.append(delta)
                    print(delta, end="", flush=True)
            except json.JSONDecodeError:
                # Certaines implémentations envoient des lignes non-JSON
                continue

        print()  # newline final
        return "".join(out)
    

_DIR = os.path.dirname(os.path.abspath(__file__))

def execute_code_from(nl, filter_path, tools):

    def read_md_file(filename: str) -> str:
        path = os.path.join(_DIR, filename)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
        
    use_stream = os.getenv("LLAMA_STREAM", "1") == "1"

    user_pref = tools["read_memory"](**{"category": "#PREFERENCE UTILISATEUR:"})
    print("Préférences utilisateur:", user_pref)
    user_pref = "\n\nVoici les préférences de l'utilisateur:\n" + "\n".join(user_pref) + "\n\n"
    system_prompt = user_pref + read_md_file(filter_path+".md")

    user_input = nl
    answer = chat_once(system_prompt, user_input, stream=use_stream)
    parsed_answer = json.loads(answer)
    capacite = parsed_answer.get("capacite")
    if capacite == "autre":
        answer = chat_once("Tu es un gentil assistant"+user_pref, user_input, stream=use_stream)
        return answer
    else:
        md_content = read_md_file(capacite+".md")
        answer = chat_once(md_content, user_input, stream=use_stream)
        parsed_answer = json.loads(answer)
        tool_name = parsed_answer.get("tool_name")
        arguments = parsed_answer.get("arguments", {})
        if tool_name in tools:
            result = tools[tool_name](**arguments)
            if tool_name == "read_memory":
                if isinstance(result, list):
                    data_str = result[-1] if result else "aucune donnée"
                elif isinstance(result, dict):
                    data_str = "\n".join(f"{k} {v[-1] if v else 'vide'}" for k, v in result.items())
                else:
                    data_str = str(result)
                response = chat_once(
                    "Tu es un assistant factuel. Réponds en une seule phrase courte. Rapporte la valeur telle quelle, sans interprétation.",
                    f"Question: {user_input}\nValeur: {data_str}",
                    stream=use_stream
                )
                return response
            return result

    if not use_stream:
        print(answer)
    return answer

