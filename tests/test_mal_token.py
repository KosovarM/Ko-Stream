from unittest.mock import patch

from kostream.mal import MalConfig, _exchange_code, _token_request


def test_token_request_uses_basic_auth_only():
    captured: dict = {}

    def fake_urlopen(req, timeout=0):
        captured["auth"] = req.headers.get("Authorization")
        captured["body"] = req.data.decode("utf-8")

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self):
                return (
                    b'{"token_type":"Bearer","expires_in":3600,'
                    b'"access_token":"at","refresh_token":"rt"}'
                )

        return Resp()

    cfg = MalConfig(
        client_id="a" * 32,
        client_secret="b" * 64,
        redirect_uri="http://127.0.0.1:5001/auth/mal/callback",
    )
    body = b"grant_type=authorization_code&code=abc&redirect_uri=x&code_verifier=y"

    with patch("kostream.mal.urlopen", fake_urlopen):
        _token_request(cfg, body)

    assert captured["auth"].startswith("Basic ")
    assert "client_secret" not in captured["body"]
    assert "client_id" not in captured["body"]


def test_exchange_code_body_has_no_client_secret():
    cfg = MalConfig(
        client_id="c" * 32,
        client_secret="d" * 64,
        redirect_uri="http://127.0.0.1:5001/auth/mal/callback",
    )
    payload = {
        "token_type": "Bearer",
        "expires_in": 3600,
        "access_token": "access",
        "refresh_token": "refresh",
    }

    with patch("kostream.mal._token_request", return_value=payload) as mock_token:
        tokens = _exchange_code(cfg, "authcode", "verifier" * 6)

    body = mock_token.call_args[0][1].decode("utf-8")
    assert "client_secret" not in body
    assert tokens.access_token == "access"
