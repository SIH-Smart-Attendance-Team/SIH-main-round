"""Pytest configuration and shared fixtures."""

import asyncio

import pytest


@pytest.fixture(scope="session")
def event_loop():
    """Override the default event loop for pytest-asyncio."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# Common test markers
pytestmark = pytest.mark.asyncio
