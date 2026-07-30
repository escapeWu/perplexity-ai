"""
Custom exceptions for Perplexity AI library.

This module defines all custom exceptions used throughout the library
for better error handling and debugging.
"""


class PerplexityError(Exception):
    """Base exception for all Perplexity AI errors."""

    pass


class ValidationError(PerplexityError):
    """Raised when input validation fails."""

    pass
