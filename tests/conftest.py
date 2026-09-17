import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client():
    settings = Settings(_env_file=None, openrouter_api_key=None)  # no model, no MCP in tests
    with TestClient(create_app(settings)) as c:
        yield c
