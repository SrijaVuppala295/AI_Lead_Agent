"""
ai_router.py — Multi-Provider AI Key Rotation
===============================================
Rotates between Groq, DeepSeek, OpenRouter.
If one hits rate limit → switches to next automatically.
If all exhausted → waits 90-120s → retries from first.

Each provider gets its own random delay after each call
to avoid pattern detection and rate limit hits.
"""

import os
import time
import requests
from groq import Groq
from utils.rate_limiter import wait, get_delay, rand


# ── Provider configs ──────────────────────────────────────────────────────
def get_providers():
    providers = []

    groq_keys = [k.strip() for k in os.getenv("GROQ_API_KEY", "").split(",") if k.strip()]
    for key in groq_keys:
        providers.append({"name": "groq", "key": key, "fails": 0})

    ds_keys = [k.strip() for k in os.getenv("DEEPSEEK_API_KEY", "").split(",") if k.strip()]
    for key in ds_keys:
        providers.append({"name": "deepseek", "key": key, "fails": 0})

    or_keys = [k.strip() for k in os.getenv("OPENROUTER_API_KEY", "").split(",") if k.strip()]
    for key in or_keys:
        providers.append({"name": "openrouter", "key": key, "fails": 0})

    return providers


# ── Main call ─────────────────────────────────────────────────────────────
def call_ai(prompt, system="You are a helpful assistant.", max_tokens=1000):
    """
    Sends prompt with automatic provider rotation + random delays.

    Per-call delays (randomized):
      Groq:       1.0 – 3.0s
      DeepSeek:   1.5 – 3.5s
      OpenRouter: 1.5 – 3.5s

    On rate limit → rotate provider + wait 60-90s
    All exhausted → wait 90-120s → retry from beginning
    """
    providers = get_providers()
    if not providers:
        raise Exception("No AI API keys configured in .env")

    current    = 0
    retries    = 0
    max_retries = len(providers) * 2

    while retries < max_retries:
        provider = providers[current % len(providers)]

        try:
            if provider["name"] == "groq":
                response = _call_groq(provider["key"], system, prompt, max_tokens)
                wait("groq")  # 1.0 – 3.0s random after each Groq call

            elif provider["name"] == "deepseek":
                response = _call_deepseek(provider["key"], system, prompt, max_tokens)
                wait("deepseek")  # 1.5 – 3.5s

            elif provider["name"] == "openrouter":
                response = _call_openrouter(provider["key"], system, prompt, max_tokens)
                wait("openrouter")  # 1.5 – 3.5s

            else:
                current += 1
                continue

            provider["fails"] = 0
            return response

        except Exception as e:
            err = str(e).lower()
            provider["fails"] += 1

            if "rate" in err or "quota" in err or "429" in err or "limit" in err:
                d = get_delay("ai_rate_limit")  # 60-90s
                print(f"  ⚠️  {provider['name']} rate limited → rotating (wait {d:.2f}s)...")
                current += 1
                retries += 1
                time.sleep(d)

                # Cycled through all providers once → long wait
                if current % len(providers) == 0:
                    d2 = get_delay("ai_all_exhausted")  # 90-120s
                    print(f"  ⏳ All providers hit limits — waiting {d2:.2f}s...")
                    time.sleep(d2)
            else:
                d = get_delay("ai_error")  # 2-5s
                print(f"  ❌ {provider['name']} error: {e} (wait {d:.2f}s)")
                current += 1
                retries += 1
                time.sleep(d)

    raise Exception("All AI providers exhausted after retries")


def _call_groq(api_key, system, prompt, max_tokens):
    client = Groq(api_key=api_key)
    resp = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt}
        ],
        temperature=0.7,
        max_tokens=max_tokens
    )
    return resp.choices[0].message.content.strip()


def _call_deepseek(api_key, system, prompt, max_tokens):
    resp = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.7
        },
        timeout=30
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _call_openrouter(api_key, system, prompt, max_tokens):
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://strikin.com",
            "X-Title": "Strikin Lead Gen Agent"
        },
        json={
            "model": "deepseek/deepseek-chat",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.7
        },
        timeout=30
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()