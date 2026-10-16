#!/usr/bin/env python3
"""Nally.com entrypoint."""
from __future__ import annotations

import os

import uvicorn

from nally.config import PORT
from nally.core.logging import logger


def main():
    port = int(os.getenv("PORT", PORT))
    logger.info("Starting Nally.com on 0.0.0.0:%s", port)
    uvicorn.run("nally.api.app:app", host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
