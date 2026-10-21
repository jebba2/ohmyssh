"""Tests for SSH config parsing and the app-managed host store."""

import tomllib
from pathlib import Path

import pytest

from pyommyssh.core.forwards import ForwardKind, PortForward
from pyommyssh.core.hosts import (
    Host,
    HostSource,
    HostStore,
    loadSshConfig,
    mergeHosts,
    parseSshConfig,
)


def test_parse_basic_host(tmp_path: Path) -> None:
    text = """
Host web
    HostName 10.0.0.5
    User deploy
    Port 2222
    IdentityFile ~/.ssh/web_key
    ProxyJump bastion
"""
    hosts = parseSshConfig(text, home=tmp_path)
    assert len(hosts) == 1
    host = hosts[0]
    assert host.name == "web"
    assert host.hostname == "10.0.0.5"
    assert host.user == "deploy"
    assert host.port == 2222
    assert host.identityFile == tmp_path / ".ssh" / "web_key"
    assert host.proxyJump == "bastion"
    assert host.source == HostSource.SSH_CONFIG


def test_hostname_defaults_to_alias(tmp_path: Path) -> None:
    hosts = parseSshConfig("Host box\n    User root\n", home=tmp_path)
    assert hosts[0].hostname == "box"
    assert hosts[0].port == 22
    assert hosts[0].identityFile is None
    assert hosts[0].proxyJump is None


def test_wildcard_and_match_blocks_are_skipped(tmp_path: Path) -> None:
    text = """
Host *
    User globaluser
    Port 9999
Host prod-?
    User wild
Match host foo
    User matched
Host real
    HostName real.example.com
"""
    hosts = parseSshConfig(text, home=tmp_path)
    assert [h.name for h in hosts] == ["real"]
    assert hosts[0].user is None
    assert hosts[0].port == 22


def test_keywords_are_case_insensitive_and_accept_equals(tmp_path: Path) -> None:
    text = "host=alpha\nhostname = alpha.local\nUSER=me\nPORT=23\n"
    hosts = parseSshConfig(text, home=tmp_path)
    assert hosts[0].hostname == "alpha.local"
    assert hosts[0].user == "me"
    assert hosts[0].port == 23


def test_inline_comments_and_invalid_port(tmp_path: Path) -> None:
    text = """
# leading comment
Host beta  # trailing comment
    HostName beta.local # another
    Port notanumber
"""
    hosts = parseSshConfig(text, home=tmp_path)
    assert hosts[0].hostname == "beta.local"
    assert hosts[0].port == 22


def test_multiple_patterns_on_one_host_line(tmp_path: Path) -> None:
    hosts = parseSshConfig("Host one two *.wild\n    User shared\n", home=tmp_path)
    assert [h.name for h in hosts] == ["one", "two"]
    assert all(h.user == "shared" for h in hosts)


def test_include_resolves_relative_to_ssh_dir(tmp_path: Path) -> None:
    sshDir = tmp_path / ".ssh"
    confD = sshDir / "conf.d"
    confD.mkdir(parents=True)
    (confD / "a.conf").write_text("Host inc-a\n    HostName a.local\n")
    (confD / "b.conf").write_text("Host inc-b\n    HostName b.local\n")
    (sshDir / "config").write_text("Host main\n    HostName main.local\nInclude conf.d/*.conf\n")
    hosts = loadSshConfig(sshDir / "config", home=tmp_path)
    assert [h.name for h in hosts] == ["main", "inc-a", "inc-b"]


def test_include_cycle_does_not_recurse_forever(tmp_path: Path) -> None:
    sshDir = tmp_path / ".ssh"
    sshDir.mkdir()
    (sshDir / "config").write_text("Include loop\nHost top\n")
    (sshDir / "loop").write_text("Include config\nHost looped\n")
    hosts = loadSshConfig(sshDir / "config", home=tmp_path)
    assert [h.name for h in hosts] == ["looped", "top"]


def test_missing_ssh_config_returns_empty(tmp_path: Path) -> None:
    assert loadSshConfig(tmp_path / ".ssh" / "config", home=tmp_path) == []


def test_host_store_round_trip(tmp_path: Path) -> None:
    storePath = tmp_path / "hosts.toml"
    store = HostStore(storePath)
    assert store.hosts() == []

    host = Host(name="db", hostname="db.local", user="pg", port=22, tags=["prod", "db"])
    store.add(host)
    store.save()

    reloaded = HostStore(storePath)
    reloaded.load()
    assert reloaded.hosts() == [host]
    assert reloaded.hosts()[0].source == HostSource.APP


def test_host_store_update_and_remove(tmp_path: Path) -> None:
    store = HostStore(tmp_path / "hosts.toml")
    store.add(Host(name="a", hostname="a.local"))
    store.add(Host(name="b", hostname="b.local"))

    store.update("a", Host(name="a2", hostname="a2.local", user="x"))
    assert [h.name for h in store.hosts()] == ["a2", "b"]

    store.remove("b")
    assert [h.name for h in store.hosts()] == ["a2"]


def test_host_store_rejects_duplicate_names(tmp_path: Path) -> None:
    store = HostStore(tmp_path / "hosts.toml")
    store.add(Host(name="a", hostname="a.local"))
    with pytest.raises(ValueError, match="already exists"):
        store.add(Host(name="a", hostname="other"))


def test_host_store_load_missing_file_is_empty(tmp_path: Path) -> None:
    store = HostStore(tmp_path / "nope" / "hosts.toml")
    store.load()
    assert store.hosts() == []


def test_host_store_save_creates_parent_dir(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "dir" / "hosts.toml"
    store = HostStore(path)
    store.add(Host(name="a", hostname="a.local"))
    store.save()
    assert path.exists()


def test_merge_hosts_app_overrides_ssh_config_by_name() -> None:
    fromConfig = [
        Host(name="shared", hostname="old.local", source=HostSource.SSH_CONFIG),
        Host(name="only-config", hostname="c.local", source=HostSource.SSH_CONFIG),
    ]
    fromApp = [
        Host(name="shared", hostname="new.local", source=HostSource.APP),
        Host(name="only-app", hostname="a.local", source=HostSource.APP),
    ]
    merged = mergeHosts(fromConfig, fromApp)
    assert [h.name for h in merged] == ["shared", "only-config", "only-app"]
    assert merged[0].hostname == "new.local"


def test_host_display_address() -> None:
    assert Host(name="x", hostname="h", user="u", port=22).displayAddress() == "u@h"
    assert Host(name="x", hostname="h", port=2200).displayAddress() == "h:2200"
    assert Host(name="x", hostname="h", user="u", port=2200).displayAddress() == "u@h:2200"


def test_parse_forward_directives(tmp_path: Path) -> None:
    text = """
Host web
    LocalForward 8080 localhost:80
    LocalForward 127.0.0.1:5432 db.internal:5432
    RemoteForward 9000 127.0.0.1:3000
    DynamicForward 1080
    DynamicForward 0.0.0.0:1081
    LocalForward /tmp/sock localhost:80
    LocalForward notaport localhost:80
"""
    hosts = parseSshConfig(text, home=tmp_path)
    assert [(f.kind, f.spec()) for f in hosts[0].forwards] == [
        (ForwardKind.LOCAL, "8080:localhost:80"),
        (ForwardKind.LOCAL, "127.0.0.1:5432:db.internal:5432"),
        (ForwardKind.REMOTE, "9000:127.0.0.1:3000"),
        (ForwardKind.DYNAMIC, "1080"),
        (ForwardKind.DYNAMIC, "0.0.0.0:1081"),
    ]


def test_forward_directives_attach_to_each_host_on_the_line(tmp_path: Path) -> None:
    hosts = parseSshConfig("Host one two\n    LocalForward 8080 localhost:80\n", home=tmp_path)
    assert all(len(host.forwards) == 1 for host in hosts)
    assert hosts[0].forwards is not hosts[1].forwards


def test_host_store_round_trips_forwards(tmp_path: Path) -> None:
    storePath = tmp_path / "hosts.toml"
    store = HostStore(storePath)
    host = Host(
        name="web",
        hostname="web.local",
        forwards=[
            PortForward.parse(ForwardKind.LOCAL, "8080:localhost:80"),
            PortForward.parse(ForwardKind.REMOTE, "9000:127.0.0.1:3000"),
            PortForward.parse(ForwardKind.DYNAMIC, "1080"),
        ],
    )
    store.add(host)
    store.save()
    with storePath.open("rb") as handle:
        written = tomllib.load(handle)["hosts"][0]
    assert written["local_forwards"] == ["8080:localhost:80"]
    assert written["remote_forwards"] == ["9000:127.0.0.1:3000"]
    assert written["dynamic_forwards"] == ["1080"]

    reloaded = HostStore(storePath)
    reloaded.load()
    assert reloaded.hosts()[0].forwards == host.forwards


def test_host_store_omits_empty_forward_lists(tmp_path: Path) -> None:
    storePath = tmp_path / "hosts.toml"
    store = HostStore(storePath)
    store.add(Host(name="a", hostname="a.local"))
    store.save()
    assert "forwards" not in storePath.read_text()


def test_host_store_skips_invalid_stored_forwards(tmp_path: Path) -> None:
    storePath = tmp_path / "hosts.toml"
    storePath.write_text('[[hosts]]\nname = "a"\nhostname = "a.local"\nlocal_forwards = ["bad", "8080:localhost:80"]\n')
    store = HostStore(storePath)
    store.load()
    assert [f.spec() for f in store.hosts()[0].forwards] == ["8080:localhost:80"]


def test_host_has_forwards() -> None:
    assert not Host(name="a", hostname="a.local").hasForwards()
    forward = PortForward.parse(ForwardKind.DYNAMIC, "1080")
    assert Host(name="a", hostname="a.local", forwards=[forward]).hasForwards()
