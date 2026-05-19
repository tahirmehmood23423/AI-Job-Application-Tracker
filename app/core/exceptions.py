"""
Custom exceptions used throughout the parser pipeline.

These are caught by the FastAPI exception handlers in main.py and translated
into appropriate HTTP responses, so callers always get clean error messages
instead of raw tracebacks.
"""


class ParserError(Exception):
    """Base class for all parser-specific errors."""


class UnsupportedFileTypeError(ParserError):
    """File extension is not supported (only PDF and DOCX allowed)."""


class FileTooLargeError(ParserError):
    """File exceeds MAX_FILE_SIZE_MB."""


class EmptyFileError(ParserError):
    """File is empty or contains no extractable text."""


class TextExtractionError(ParserError):
    """Failed to extract text from the uploaded file (corrupt, encrypted, etc.)."""


class LLMExtractionError(ParserError):
    """The LLM call failed or returned invalid JSON after retries."""


class LLMConfigurationError(ParserError):
    """LLM credentials are missing or misconfigured at startup."""
