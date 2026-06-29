import logging
from datetime import datetime, timezone
from typing import Any, Optional

try:
    from curl_cffi import requests as cf_requests
    _HAS_CFFI = True
except ImportError:
    import requests as cf_requests
    _HAS_CFFI = False

from backend.config import GATEWAY_URL, OUTER_HEADERS, HTML_HEADERS
from backend.core.exceptions import TokenExpiredError, NetworkError

logger = logging.getLogger("novel_downloader.client")


class FictionZoneClient:
    """HTTP client for fictionzone.net gateway and public HTML endpoints.

    Authentication is solely via the Bearer JWT token placed in the inner
    request payload's authorization header.  No cookies are needed — the
    diagnostic script confirmed the Bearer token alone yields full content.
    """

    def __init__(self, token: str):
        # Normalise: always prefix with 'Bearer '
        if token and not token.startswith("Bearer "):
            token = f"Bearer {token}"
        self.token = token

    @property
    def has_cffi(self) -> bool:
        return _HAS_CFFI

    @property
    def backend_name(self) -> str:
        return "curl_cffi" if _HAS_CFFI else "requests"

    def _now_iso(self) -> str:
        """ISO-8601 UTC timestamp with millisecond precision."""
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

    def _build_inner_payload(self, path: str, query: Optional[dict] = None) -> dict:
        """Build the inner routing instruction that goes in the POST body.

        This mirrors exactly what diagnose_api.py does: the authorization token
        lives INSIDE the payload headers, not in the outer HTTP headers.
        """
        headers = [
            ["authorization", self.token or ""],
            ["x-request-time", self._now_iso()],
        ]
        return {
            "path": path,
            "method": "GET",
            "query": query or {},
            "headers": headers,
        }

    def _post_kwargs(self, json_body: dict, timeout: int) -> dict:
        """Build keyword arguments for the outer HTTP POST.

        Only standard browser headers are sent here — no cookie injection.
        The authentication is handled by the inner payload's authorization header.
        """
        kwargs: dict[str, Any] = {
            "headers": {**OUTER_HEADERS},
            "json": json_body,
            "timeout": timeout,
        }
        if _HAS_CFFI:
            kwargs["impersonate"] = "chrome120"
        return kwargs

    def post_gateway(self, path: str, query: Optional[dict] = None, timeout: int = 15) -> dict:
        """POST the inner routing instruction and return the parsed JSON response.

        Raises:
            TokenExpiredError: when server returns 401 Unauthorized.
            NetworkError: on other HTTP or transport failures.
        """
        inner = self._build_inner_payload(path, query)
        kwargs = self._post_kwargs(inner, timeout=timeout)

        try:
            response = cf_requests.post(GATEWAY_URL, **kwargs)
        except Exception as err:
            logger.error(f"Transport error posting to gateway: {err}")
            raise NetworkError(f"Transport error: {err}") from err

        # Handle HTTP level errors
        if response.status_code == 401:
            logger.warning("Gateway returned 401 Unauthorized - token is expired or invalid")
            raise TokenExpiredError("Token is expired or invalid")

        if response.status_code >= 400:
            logger.error(f"Gateway returned HTTP error {response.status_code}: {response.reason}")
            raise NetworkError(f"HTTP error {response.status_code}: {response.reason}")

        try:
            resp_data = response.json()
        except ValueError as err:
            logger.error("Gateway response is not valid JSON")
            raise NetworkError("Invalid JSON response from gateway") from err

        # Check for application level errors inside response
        if not resp_data.get("success"):
            error_msg = resp_data.get("error") or resp_data.get("reason") or resp_data.get("message") or "Unknown error"
            status_code = resp_data.get("status_code") or resp_data.get("code")

            if status_code == 401 or "unauthorized" in error_msg.lower() or "token" in error_msg.lower():
                logger.warning(f"Application error implies token expiry: {error_msg}")
                raise TokenExpiredError(f"Token expired application error: {error_msg}")

            logger.error(f"Application failure from gateway: {error_msg}")
            raise NetworkError(f"Gateway error: {error_msg}")

        return resp_data

    def get_html(self, url: str, timeout: int = 20) -> str:
        """GET a public HTML page with browser-like TLS and return the decoded text."""
        kwargs: dict[str, Any] = {"headers": HTML_HEADERS, "timeout": timeout}
        if _HAS_CFFI:
            kwargs["impersonate"] = "chrome120"
        try:
            response = cf_requests.get(url, **kwargs)
            response.raise_for_status()
            return response.text
        except Exception as err:
            logger.error(f"Error fetching HTML from {url}: {err}")
            raise NetworkError(f"Error fetching HTML: {err}") from err

    def get_bytes(self, url: str, timeout: int = 20) -> bytes:
        """GET a binary resource (e.g. cover image) and return raw bytes."""
        kwargs: dict[str, Any] = {"headers": HTML_HEADERS, "timeout": timeout}
        if _HAS_CFFI:
            kwargs["impersonate"] = "chrome120"
        try:
            response = cf_requests.get(url, **kwargs)
            response.raise_for_status()
            return response.content
        except Exception as err:
            logger.error(f"Error fetching binary bytes from {url}: {err}")
            raise NetworkError(f"Error fetching binary: {err}") from err
