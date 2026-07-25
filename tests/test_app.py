from localstream.app import create_app


def test_home_loads():
    app = create_app()
    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"LocalWatch" in resp.data or b"Spotlight" in resp.data


def test_search():
    app = create_app()
    client = app.test_client()
    resp = client.get("/search?q=demo")
    assert resp.status_code == 200
