import os
from pathlib import Path

# Base Directories
BACKEND_DIR = Path(__file__).resolve().parent
APP_DIR = BACKEND_DIR.parent
WORKSPACE_DIR = APP_DIR.parent

# Books folder is at the workspace root to remain backward compatible
BOOKS_DIR = WORKSPACE_DIR / "books"

# Default Scraper Settings
DEFAULT_DELAY_MIN = 2.0
DEFAULT_DELAY_MAX = 6.0
DEFAULT_TIMEOUT = 15
DEFAULT_MAX_FAILURES = 5

# API Endpoints
GATEWAY_URL = "https://fictionzone.net/api/__api_party/fictionzone"
SITE_ORIGIN = "https://fictionzone.net"

# --- Load token from .env ---
def _load_env_token() -> str:
    """Read FICTIONZONE_TOKEN from .env file next to main.py, or fall back to env var."""
    env_path = APP_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("FICTIONZONE_TOKEN="):
                token = line[len("FICTIONZONE_TOKEN="):].strip()
                # Ensure Bearer prefix
                if token and not token.startswith("Bearer "):
                    token = f"Bearer {token}"
                return token
    # Fallback to environment variable
    token = os.environ.get("FICTIONZONE_TOKEN", "")
    if token and not token.startswith("Bearer "):
        token = f"Bearer {token}"
    return token


FICTIONZONE_TOKEN: str = _load_env_token()

# Browser Headers for outer requests (Cloudflare bypass)
OUTER_HEADERS = {
    "accept": "application/json",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "content-type": "application/json",
    "origin": SITE_ORIGIN,
    "priority": "u=1, i",
    "referer": f"{SITE_ORIGIN}/",
    "sec-ch-ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
    ),
}

# Headers used when fetching the public HTML page (book info)
HTML_HEADERS = {
    **OUTER_HEADERS,
    "accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "accept-encoding": "gzip, deflate, br, zstd",
}

# Ensure folders exist
BOOKS_DIR.mkdir(parents=True, exist_ok=True)
