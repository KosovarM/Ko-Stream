from kostream.mal import format_last_sync_label, load_last_sync, record_last_sync


def test_record_and_format_last_sync(tmp_path, monkeypatch):
    from kostream import mal as mal_mod

    monkeypatch.setattr(mal_mod, "MAL_DATA_DIR", tmp_path)
    monkeypatch.setattr(mal_mod, "LAST_SYNC_FILE", tmp_path / "last_sync.json")

    stamp = record_last_sync(42)
    assert stamp.endswith("Z")
    data = load_last_sync()
    assert data is not None
    assert data["count"] == 42
    label = format_last_sync_label(data)
    assert label is not None
    assert "Last sync:" in label
    assert "42 anime" in label


def test_format_last_sync_none():
    assert format_last_sync_label(None) is None
