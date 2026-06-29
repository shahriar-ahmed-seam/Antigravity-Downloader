class ScraperException(Exception):
    """Base exception for the novel downloader pipeline."""
    pass


class TokenExpiredError(ScraperException):
    """Raised when the authorization token has expired or is invalid (401 Unauthorized)."""
    pass


class NetworkError(ScraperException):
    """Raised when transport/connection errors occur during gateway communications."""
    pass


class BookParseError(ScraperException):
    """Raised when metadata or IDs cannot be parsed from the novel HTML page."""
    pass


class EpubBuildError(ScraperException):
    """Raised when assembly of the EPUB file fails."""
    pass
