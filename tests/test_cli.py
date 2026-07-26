"""CLI helpers for LAN / serve banners."""

from kostream.cli import _is_loopback, _lan_ipv4_addresses, _sanitize_mdns_name


def test_is_loopback():
    assert _is_loopback("127.0.0.1")
    assert _is_loopback("localhost")
    assert not _is_loopback("0.0.0.0")
    assert not _is_loopback("192.168.1.10")


def test_lan_ipv4_addresses_returns_list():
    addrs = _lan_ipv4_addresses()
    assert isinstance(addrs, list)
    for ip in addrs:
        assert not ip.startswith("127.")


def test_sanitize_mdns_name():
    assert _sanitize_mdns_name("KoStream") == "kostream"
    assert _sanitize_mdns_name("Ko Stream!") == "ko-stream"
    assert _sanitize_mdns_name("") == "kostream"
