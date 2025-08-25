import os, time, random
from typing import List
from openai import OpenAI
from openai import RateLimitError, APIStatusError

_client = None

def _client_ok() -> OpenAI:
    global _client
    if _client is None:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        _client = OpenAI(api_key=key)
    return _client

def _retry_sleep(attempt: int):
    # экспоненциальный бекофф с джиттером
    base = min(2 ** attempt, 30)
    time.sleep(base + random.uniform(0, 0.5))

def embed_texts(texts: List[str],
                model: str | None = None,
                max_retries: int | None = None) -> List[List[float]]:
    client = _client_ok()
    model = model or os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
    max_retries = int(os.getenv("OPENAI_RETRY", "4")) if max_retries is None else max_retries

    for attempt in range(max_retries + 1):
        try:
            res = client.embeddings.create(model=model, input=texts)
            return [d.embedding for d in res.data]
        except RateLimitError:
            if attempt >= max_retries:
                # мягкий фолбэк: вернём нули, чтобы пайплайн не падал
                dim = 1536  # размерность t-e-3-small
                return [[0.0] * dim for _ in texts]
            _retry_sleep(attempt)
        except APIStatusError as e:
            # 429 или 5xx
            if getattr(e, "status_code", 0) in (429, 500, 502, 503, 504):
                if attempt >= max_retries:
                    dim = 1536
                    return [[0.0] * dim for _ in texts]
                _retry_sleep(attempt)
            else:
                raise

def chat(system: str, user: str,
         model: str | None = None,
         max_tokens: int = 800,
         temperature: float = 0.3) -> str:
    client = _client_ok()
    model = model or os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    max_retries = int(os.getenv("OPENAI_RETRY", "4"))

    for attempt in range(max_retries + 1):
        try:
            res = client.chat.completions.create(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
            )
            return (res.choices[0].message.content or "").strip()
        except RateLimitError:
            if attempt >= max_retries:
                # мягкий фолбэк: вернём пусто
                return "⏳ Лимит генерации временно исчерпан."
            _retry_sleep(attempt)
        except APIStatusError as e:
            if getattr(e, "status_code", 0) in (429, 500, 502, 503, 504):
                if attempt >= max_retries:
                    return "⏳ Лимит генерации временно исчерпан."
                _retry_sleep(attempt)
            else:
                raise
