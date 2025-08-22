from __future__ import annotations
import os, json, io
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

def _drive_service():
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set")
    info = json.loads(raw)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def download_text(file_id: str) -> str:
    svc = _drive_service()
    meta = svc.files().get(fileId=file_id, fields="id,name,mimeType").execute()
    mime = meta.get("mimeType")
    if mime == "application/vnd.google-apps.document":
        data = svc.files().export(fileId=file_id, mimeType="text/plain").execute()
        return data.decode("utf-8", errors="ignore") if isinstance(data, bytes) else str(data)
    req = svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue().decode("utf-8", errors="ignore")
