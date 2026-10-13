"""Talk to LLMFlow with the official OpenAI Python SDK.

    pip install openai
    export LLMFLOW_KEY=<a value from LLMFLOW_API_KEYS in backend/.env>
    python examples/openai_quickstart.py

Optional: LLMFLOW_URL (default http://localhost:8000/v1)
"""

from __future__ import annotations

import os
import sys
import time

from openai import APIStatusError, AuthenticationError, OpenAI

BASE_URL = os.environ.get("LLMFLOW_URL", "http://localhost:8000/v1")
KEY = os.environ.get("LLMFLOW_KEY", "")
if not KEY:
    sys.exit("Set LLMFLOW_KEY to one of the values in LLMFLOW_API_KEYS (backend/.env).")

client = OpenAI(base_url=BASE_URL, api_key=KEY)  # the only change vs. calling OpenAI directly


def section(title: str) -> None:
    print(f"\n=== {title} ===")


section("1. Models the gateway exposes")
for m in client.models.list().data:
    print(" -", m.id)

section("2. A routed request (model='auto')")
raw = client.chat.completions.with_raw_response.create(
    model="auto",
    max_tokens=300,
    messages=[{"role": "user", "content": "What is the capital of Japan? One word."}],
)
reply = raw.parse()
print("reply:", reply.choices[0].message.content)
print("served by:", raw.headers.get("x-llmflow-model"), "| attempts:", raw.headers.get("x-llmflow-attempts"))
print("why:", raw.headers.get("x-llmflow-route-reason"))
print("shadow cost (USD):", raw.headers.get("x-llmflow-shadow-cost-usd"))

section("3. Quality dial: same kind of prompt, quality='high'")
raw = client.chat.completions.with_raw_response.create(
    model="auto",
    max_tokens=1200,
    messages=[{"role": "user", "content": "Compare optimistic and pessimistic locking step by step, then give a recommendation."}],
    extra_body={"llmflow": {"quality": "high"}},
)
print("served by:", raw.headers.get("x-llmflow-model"))
print("why:", raw.headers.get("x-llmflow-route-reason"))

section("4. Streaming")
start = time.time()
first = None
text = []
for event in client.chat.completions.create(
    model="auto", max_tokens=300, stream=True,
    messages=[{"role": "user", "content": "Count from 1 to 5."}],
):
    if event.choices and event.choices[0].delta.content:
        first = first or time.time() - start
        text.append(event.choices[0].delta.content)
print("streamed:", "".join(text).strip().replace("\n", " "))
print(f"first token after {first:.2f}s" if first else "no tokens")

section("5. Response cache (temperature=0, same request twice)")
body = dict(
    model="auto", max_tokens=100, temperature=0,
    messages=[{"role": "user", "content": f"Reply with the word OK. ({int(time.time())})"}],
)
a = client.chat.completions.with_raw_response.create(**body)
b = client.chat.completions.with_raw_response.create(**body)
print("first :", a.headers.get("x-llmflow-cache"), "| attempts", a.headers.get("x-llmflow-attempts"))
print("second:", b.headers.get("x-llmflow-cache"), "| attempts", b.headers.get("x-llmflow-attempts"))

section("6. Pin a specific model, and what errors look like")
pinned = client.chat.completions.with_raw_response.create(
    model="groq-gpt-oss-120b", max_tokens=200,
    messages=[{"role": "user", "content": "Say hi."}],
)
print("pinned ->", pinned.headers.get("x-llmflow-model"))
try:
    client.chat.completions.create(model="no-such-model", messages=[{"role": "user", "content": "x"}])
except APIStatusError as e:
    print("unknown model ->", type(e).__name__, e.status_code)
try:
    OpenAI(base_url=BASE_URL, api_key="definitely-wrong-key-0123456789").models.list()
except AuthenticationError as e:
    print("wrong key     ->", type(e).__name__, e.status_code)

print("\nDone. Open the dashboard Requests page to see all of these.")
