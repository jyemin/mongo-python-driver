from __future__ import annotations

import pytest
import pytest_asyncio
from pymongo import AsyncMongoClient


@pytest_asyncio.fixture(scope="module")
async def db():
    client = AsyncMongoClient("mongodb://localhost:27017")
    try:
        yield client.get_database("mqlv2_test")
    finally:
        await client.aclose()
