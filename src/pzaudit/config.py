from __future__ import annotations
import os
from pathlib import Path
APP_ID=108600
DEFAULT_DB_PATH=Path("data/pzaudit.db")
STEAM_QUERY_URL="https://api.steampowered.com/IPublishedFileService/QueryFiles/v1/"
def get_api_key():
    key=os.environ.get("STEAM_WEB_API_KEY","").strip()
    if not key: raise RuntimeError("STEAM_WEB_API_KEY is not set.")
    return key
