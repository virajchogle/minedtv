import pytest
from fastapi.testclient import TestClient

from app.api.auth import key_matches
from app.config import Settings
from app.main import create_app

KEYS = ["k-primary", "k-rotating"]


@pytest.fixture
def client():
    app = create_app(Settings(api_keys=KEYS, cors_origins=["*"]))
    # No lifespan (no DB/Redis); routes past the key check may error, which is fine here.
    return TestClient(app, raise_server_exceptions=False)


def test_key_matches():
    assert key_matches("k-primary", KEYS)
    assert key_matches("k-rotating", KEYS)
    assert not key_matches("k-primar", KEYS)
    assert not key_matches("", KEYS)
    assert not key_matches(None, KEYS)


@pytest.mark.parametrize("path", ["/feed", "/search?q=clutch", "/clips/00000000-0000-0000-0000-000000000001"])
def test_protected_routes_reject_missing_or_wrong_key(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"X-API-Key": "nope"}).status_code == 401


def test_valid_key_in_header_or_query_passes(client):
    assert client.get("/feed", headers={"X-API-Key": "k-rotating"}).status_code != 401
    assert client.get("/feed?api_key=k-primary").status_code != 401


@pytest.mark.parametrize("path", ["/docs", "/openapi.json", "/clips/00000000-0000-0000-0000-000000000001/playlist.m3u8"])
def test_open_paths_skip_the_check(client, path):
    assert client.get(path).status_code != 401


def test_cors_preflight_and_401_carry_cors_headers(client):
    pre = client.options("/feed", headers={"Origin": "https://web.example", "Access-Control-Request-Method": "GET",
                                          "Access-Control-Request-Headers": "x-api-key"})
    assert pre.status_code == 200
    denied = client.get("/feed", headers={"Origin": "https://web.example"})
    assert denied.status_code == 401
    assert denied.headers.get("access-control-allow-origin") == "*"


def test_no_keys_configured_means_open():
    app = create_app(Settings(api_keys=[]))
    assert TestClient(app, raise_server_exceptions=False).get("/feed").status_code != 401
