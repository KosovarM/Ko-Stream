from unittest.mock import patch

from kostream.mal import MalConfig, extract_oauth_code, prepare_oauth, start_oauth


def test_prepare_oauth_urls(tmp_path, monkeypatch):
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "MAL_DATA_DIR", tmp_path)
    cfg = MalConfig(
        client_id="abc123",
        client_secret="secret",
        redirect_uri="http://localhost:5001/auth/mal/callback",
    )
    urls = prepare_oauth(cfg)
    assert "myanimelist.net/v1/oauth2/authorize" in urls["authorize_url"]
    assert "client_id=abc123" in urls["authorize_url"]
    assert "login.php?from=" in urls["login_first_url"]
    assert (tmp_path / "pending_oauth.json").exists()


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
    url = start_oauth(cfg)
    assert "myanimelist.net/v1/oauth2/authorize" in url
    assert "client_id=abc123" in url
    assert "code_challenge_method=plain" in url
    assert (tmp_path / "pending_oauth.json").exists()
