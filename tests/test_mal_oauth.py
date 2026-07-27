import json

import pytest

from kostream.mal import (
    MalConfig,
    MalError,
    MalTokens,
    complete_oauth,
    extract_oauth_code,
    is_connected,
    load_tokens,
    pending_oauth_path,
    prepare_oauth,
    save_tokens,
    start_oauth,
    token_path,
)


def test_prepare_oauth_urls(tmp_path, monkeypatch):
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "MAL_DATA_DIR", tmp_path)
    cfg = MalConfig(
        client_id="abc123",
        client_secret="secret",
        redirect_uri="http://localhost:5001/auth/mal/callback",
    )
    urls = prepare_oauth(cfg, "u_alice")
    assert "myanimelist.net/v1/oauth2/authorize" in urls["authorize_url"]
    assert "client_id=abc123" in urls["authorize_url"]
    assert "login.php?from=" in urls["login_first_url"]
    pending = pending_oauth_path("u_alice")
    assert pending.exists()
    assert '"user_id": "u_alice"' in pending.read_text(encoding="utf-8")


def test_extract_oauth_code():
    assert extract_oauth_code("abc123") == "abc123"
    url = "http://127.0.0.1:5001/auth/mal/callback?code=LONGCODE&state=xyz"
    assert extract_oauth_code(url) == "LONGCODE"


def test_start_oauth_builds_url(tmp_path, monkeypatch):
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "MAL_DATA_DIR", tmp_path)
    cfg = MalConfig(
        client_id="abc123",
        client_secret="secret",
        redirect_uri="http://127.0.0.1:5001/auth/mal/callback",
    )
    url = start_oauth(cfg, "u_bob")
    assert "myanimelist.net/v1/oauth2/authorize" in url
    assert "client_id=abc123" in url
    assert "code_challenge_method=plain" in url
    assert pending_oauth_path("u_bob").exists()


def test_token_paths_differ_per_user(tmp_path, monkeypatch):
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "MAL_DATA_DIR", tmp_path)
    assert token_path("u_a") != token_path("u_b")
    save_tokens(
        "u_a",
        MalTokens("a-access", "a-refresh", expires_at=9_999_999_999, username="Alice"),
    )
    save_tokens(
        "u_b",
        MalTokens("b-access", "b-refresh", expires_at=9_999_999_999, username="Bob"),
    )
    assert is_connected("u_a")
    assert is_connected("u_b")
    assert load_tokens("u_a").username == "Alice"
    assert load_tokens("u_b").username == "Bob"
    assert not (tmp_path / "tokens.json").exists()


def test_complete_oauth_refuses_wrong_user(tmp_path, monkeypatch):
    import time

    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "MAL_DATA_DIR", tmp_path)
    cfg = MalConfig(
        client_id="abc123",
        client_secret="secret",
        redirect_uri="http://127.0.0.1:5001/auth/mal/callback",
    )
    # Pending file for Bob but bound to Alice — callback must refuse.
    pending = pending_oauth_path("u_bob")
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text(
        json.dumps(
            {
                "user_id": "u_alice",
                "state": "shared-state",
                "code_verifier": "v" * 64,
                "created_at": time.time(),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(MalError, match="different user"):
        complete_oauth(cfg, "code", "shared-state", "u_bob")

def test_disconnect_one_user_leaves_other(tmp_path, monkeypatch):
    from kostream import mal as mal_mod
    from kostream.mal import disconnect

    monkeypatch.setattr(mal_mod, "MAL_DATA_DIR", tmp_path)
    save_tokens(
        "u_a",
        MalTokens("a", "ar", expires_at=9_999_999_999, username="A"),
    )
    save_tokens(
        "u_b",
        MalTokens("b", "br", expires_at=9_999_999_999, username="B"),
    )
    disconnect("u_a")
    assert not is_connected("u_a")
    assert is_connected("u_b")
    assert load_tokens("u_b").username == "B"
