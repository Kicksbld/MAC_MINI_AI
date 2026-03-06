#!/usr/bin/env python3
import os
import json
import sys
import requests

from nl_to_code import execute_code_from

import threading

MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memoire.md")
_MEMORY_LOCK = threading.Lock()

def compter(a,b):
    return a+b

def gerer_led(**kwargs):
    action = kwargs.get("action")
    couleur = kwargs.get("couleur")
    led_number = kwargs.get("led_number")
    return (action, couleur, led_number)

def read_memory(**kwargs):
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    category = kwargs.get("category", None)

    if category:
        start = content.find(category)
        if start == -1:
            return []
        start += len(category)
        end = content.find("#", start)
        if end == -1:
            end = len(content)
        return content[start:end].strip().splitlines()

    import re
    memoire_data = {}
    matches = list(re.finditer(r'^(#[^\n]+:)', content, re.MULTILINE))
    for i, match in enumerate(matches):
        cat = match.group(1)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        memoire_data[cat] = content[start:end].strip().splitlines()
    return memoire_data

def write_memory(**kwargs):
    category = kwargs.get("category", "").strip()
    if not category.endswith(":"):
        category += ":"
    content = kwargs.get("content")

    replace = kwargs.get("replace", False)

    with _MEMORY_LOCK:
        memoire_data = read_memory()

        if replace or category not in memoire_data:
            memoire_data[category] = [content]
        else:
            memoire_data[category].append(content)

        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            for cat, contents in memoire_data.items():
                f.write(cat + "\n")
                for item in contents:
                    f.write(item + "\n")
                f.write("\n")

    return memoire_data

tool_mapping = {
    "compter": compter,
    "gerer_led": gerer_led,
    "read_memory": read_memory,
    "write_memory": write_memory,
}
