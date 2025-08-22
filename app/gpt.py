import os
from typing import List
from openai import OpenAI

_client = None

def _client_ok() -> OpenAI:
    global _client
    if _client is None:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        _client = OpenAI(api_key=key)
    return _client

def embed_texts(texts: List[str], model: str = "text-embedding-3-small") -> List[List[float]]:
    client = _client_ok()
    res = client.embeddings.create(model=model, input=texts)
    return [d.embedding for d in res.data]

def chat(system: str, user: str, model: str = "gpt-4o-mini", max_tokens: int = 800, temperature: float = 0.3) -> str:
    client = _client_ok()
    res = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return (res.choices[0].message.content or "").strip()
