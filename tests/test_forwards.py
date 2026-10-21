"""Tests for port forward rules: parsing, formatting, and descriptions."""

from __future__ import annotations

import re

import pytest

from pyommyssh.core.forwards import ForwardKind, PortForward


def test_parse_local_forward_without_bind_address() -> None:
    forward = PortForward.parse(ForwardKind.LOCAL, "8080:localhost:80")
    assert forward == PortForward(
        kind=ForwardKind.LOCAL, bindPort=8080, remoteHost="localhost", remotePort=80
    )
    assert forward.spec() == "8080:localhost:80"


def test_parse_remote_forward_with_bind_address() -> None:
    forward = PortForward.parse(ForwardKind.REMOTE, " 0.0.0.0:9000:127.0.0.1:3000 ")
    assert forward.bindAddress == "0.0.0.0"
    assert forward.bindPort == 9000
    assert forward.remoteHost == "127.0.0.1"
    assert forward.remotePort == 3000
    assert forward.spec() == "0.0.0.0:9000:127.0.0.1:3000"


def test_parse_dynamic_forward() -> None:
    plain = PortForward.parse(ForwardKind.DYNAMIC, "1080")
    assert plain == PortForward(kind=ForwardKind.DYNAMIC, bindPort=1080)
    assert plain.spec() == "1080"
    bound = PortForward.parse(ForwardKind.DYNAMIC, "127.0.0.1:1080")
    assert bound.bindAddress == "127.0.0.1"
    assert bound.spec() == "127.0.0.1:1080"


def test_ipv6_addresses_keep_their_brackets() -> None:
    forward = PortForward.parse(ForwardKind.LOCAL, "[::1]:8080:[fe80::1]:80")
    assert forward.bindAddress == "::1"
    assert forward.remoteHost == "fe80::1"
    assert forward.spec() == "[::1]:8080:[fe80::1]:80"


@pytest.mark.parametrize(
    "kind, spec, message",
    [
        (ForwardKind.LOCAL, "8080", "expected [bind_address:]port:host:hostport"),
        (ForwardKind.LOCAL, "8080::80", "expected [bind_address:]port:host:hostport"),
        (ForwardKind.LOCAL, "a:b:c:d:e", "expected [bind_address:]port:host:hostport"),
        (ForwardKind.LOCAL, "0:localhost:80", "'0' is not a port between 1 and 65535"),
        (ForwardKind.LOCAL, "8080:localhost:99999", "'99999' is not a port between 1 and 65535"),
        (ForwardKind.LOCAL, "[::1:8080:host:80", "expected [bind_address:]port:host:hostport"),
        (ForwardKind.DYNAMIC, "1080:host:80", "expected [bind_address:]port"),
        (ForwardKind.DYNAMIC, "", "expected [bind_address:]port"),
    ],
)
def test_invalid_specs_raise(kind: ForwardKind, spec: str, message: str) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        PortForward.parse(kind, spec)


def test_describe_is_compact() -> None:
    assert PortForward.parse(ForwardKind.LOCAL, "8080:localhost:80").describe() == "L 8080 -> localhost:80"
    assert PortForward.parse(ForwardKind.REMOTE, "9000:127.0.0.1:3000").describe() == "R 9000 -> 127.0.0.1:3000"
    assert PortForward.parse(ForwardKind.DYNAMIC, "1080").describe() == "D 1080 (SOCKS)"
    assert PortForward.parse(ForwardKind.LOCAL, "[::1]:8080:host:80").describe() == "L [::1]:8080 -> host:80"


def test_local_bind_address_defaults_to_loopback() -> None:
    assert PortForward.parse(ForwardKind.LOCAL, "8080:localhost:80").listenAddress() == "127.0.0.1"
    assert PortForward.parse(ForwardKind.LOCAL, "0.0.0.0:8080:localhost:80").listenAddress() == "0.0.0.0"
    assert PortForward.parse(ForwardKind.LOCAL, "*:8080:localhost:80").listenAddress() == "0.0.0.0"
    assert PortForward.parse(ForwardKind.LOCAL, "localhost:8080:localhost:80").listenAddress() == "127.0.0.1"
