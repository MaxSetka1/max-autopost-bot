import os, requests

def _post(url, payload):
    try:
        r = requests.post(url, json=payload, timeout=20)
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)

def send_text(token: str|None, alias: str, text: str, api_base: str|None=None, dry_run: bool=False):
    if dry_run or not token:
        print(f"[DRY-RUN] -> {alias}: {text[:120]}...")
        return True

    url1 = f"https://api.telegram.org/bot{token}/sendMessage"
    st, body = _post(url1, {"chat_id": alias, "text": text})
    if 200 <= st < 300:
        print("[OK tg-like]", body[:200]); return True

    if api_base:
        url2 = api_base.rstrip("/") + "/sendMessage"
        st2, body2 = _post(url2, {"chat_id": alias, "text": text})
        if 200 <= st2 < 300:
            print("[OK custom]", body2[:200]); return True
        print("[ERR custom]", st2, body2[:200])
    else:
        print("[ERR tg-like]", st, body[:200])

    return False
