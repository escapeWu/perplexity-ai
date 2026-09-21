#!/usr/bin/env python3
"""Backward-compatible entry point for the unified REST client."""

from client import main


if __name__ == "__main__":
    raise SystemExit(main())
