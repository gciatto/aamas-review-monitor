import hashlib
import socket

import pytest
import requests

from aamas_review_monitor import __main__ as cli
from aamas_review_monitor import areas, core, models
from tests.test_areas import PAGE

CONFIG = {
    "embeddings_vendor": "ollama",
    "embeddings_url": "",
    "embeddings_model": "",
    "embeddings_networks": ["127.0.0.0/8", "::1/128"],
    "embeddings_retries": 5,
    "embeddings_backoff_seconds": 1,
    "embeddings_backoff_max_seconds": 60,
}


def vector(text: str) -> list[float]:
    """Bag of words, each word on a fixed dimension: texts sharing words are similar."""
    found = [0.0] * 64
    for word in text.lower().split():
        found[int(hashlib.sha256(word.strip(".,:").encode()).hexdigest(), 16) % 64] += 1
    return found


class FakeEndpoint:
    """Stands in for an OpenAI-compatible /embeddings endpoint: records the requests."""

    def __init__(self, monkeypatch):
        self.requests: list[dict] = []
        monkeypatch.setattr(
            requests.Session, "post", lambda *args, **kwargs: self.post(*args, **kwargs)
        )

    def post(self, session, url, json, timeout, allow_redirects=True):
        self.requests.append(
            {
                "url": url,
                "headers": dict(session.headers),
                "redirects": allow_redirects,
                "proxies from the environment": session.trust_env,
            }
            | json
        )
        data = [{"index": i, "embedding": vector(t)} for i, t in enumerate(json["input"])]

        class Response:
            is_redirect = False

            def raise_for_status(self):
                pass

            def json(self):
                return {"data": data[::-1]}  # any order: the index says which is which

        return Response()


def resolves_to(monkeypatch, *addresses):
    def getaddrinfo(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 0)) for a in addresses]

    monkeypatch.setattr(models.socket, "getaddrinfo", getaddrinfo)


def test_settings_come_from_given_then_environment_then_config_then_preset(monkeypatch):
    s = models.settings(CONFIG)
    assert (s.url, s.model, s.api_key) == ("http://localhost:11434/v1", "nomic-embed-text", "")
    assert s.networks == ("127.0.0.0/8", "::1/128") and s.retries == 5
    monkeypatch.setenv("AAMAS_MONITOR_EMBEDDINGS_MODEL", "nomic-embed-text")
    monkeypatch.setenv("AAMAS_MONITOR_EMBEDDINGS_NETWORKS", "10.0.0.0/8, 127.0.0.0/8")
    monkeypatch.setenv("AAMAS_MONITOR_EMBEDDINGS_RETRIES", "2")
    monkeypatch.setenv("AAMAS_MONITOR_EMBEDDINGS_API_KEY", "secret")
    s = models.settings(CONFIG, model="mxbai-embed-large", vendor="openai")
    assert (s.url, s.model, s.api_key) == (
        "https://api.openai.com/v1",
        "mxbai-embed-large",
        "secret",
    )
    assert s.networks == ("10.0.0.0/8", "127.0.0.0/8") and s.retries == 2
    assert models.settings(CONFIG | {"embeddings_api_key": "x"}, api_key=None).api_key == "secret"
    with pytest.raises(ValueError, match="not one of ollama, openai"):
        models.settings(CONFIG, vendor="acme")
    with pytest.raises(ValueError):
        models.settings(CONFIG, networks="10.0.0/33")


def test_paper_data_only_goes_to_endpoints_inside_the_allowed_networks(monkeypatch, tmp_path):
    endpoint, s = FakeEndpoint(monkeypatch), models.settings(CONFIG, url="http://gpu.lab:8080/v1")
    resolves_to(monkeypatch, "127.0.0.1", "93.184.216.34")
    with pytest.raises(PermissionError, match="93.184.216.34, outside the allowed networks"):
        models.embed(s, ["an abstract"], tmp_path, private=True)
    assert endpoint.requests == []
    models.embed(s, ["a public topic"], tmp_path, private=False)  # public text: anywhere
    resolves_to(monkeypatch, "10.1.2.3")
    lab = s._replace(networks=("10.0.0.0/8",))
    models.embed(lab, ["an abstract"], tmp_path, private=True)
    assert [r["input"] for r in endpoint.requests] == [["a public topic"], ["an abstract"]]
    assert endpoint.requests[0]["url"] == "http://gpu.lab:8080/v1/embeddings"


def test_embeddings_are_cached_per_model_and_text(monkeypatch, tmp_path):
    endpoint, s = FakeEndpoint(monkeypatch), models.settings(CONFIG, api_key="k")
    first = models.embed(s, ["b a", "c", "b a"], tmp_path, private=False)
    assert first[0] == first[2] and abs(sum(x * x for x in first[1]) - 1) < 1e-9
    assert endpoint.requests[0]["input"] == ["b a", "c"]  # each text once
    assert endpoint.requests[0]["headers"]["Authorization"] == "Bearer k"
    assert models.embed(s, ["c", "b a"], tmp_path, private=False) == [first[1], first[0]]
    assert len(endpoint.requests) == 1
    assert len(list(tmp_path.glob("*.yaml"))) == 2
    other = s._replace(model="other")
    with pytest.raises(LookupError, match="1 texts not embedded with other"):
        models.embed(other, ["c"], tmp_path, private=False, cache_only=True)
    many = [f"text {i}" for i in range(models.BATCH + 1)]
    models.embed(s, many, tmp_path, private=False)
    assert [len(r["input"]) for r in endpoint.requests[1:]] == [models.BATCH, 1]


def test_session_retries_with_backoff_from_the_settings():
    s = models.settings(CONFIG, retries=3, backoff_seconds=0.5)
    retry = models.session(s).get_adapter("http://localhost").max_retries
    assert (retry.total, retry.backoff_factor, retry.backoff_max) == (3, 0.5, 60)
    assert retry.allowed_methods is None and 429 in retry.status_forcelist


def test_confusion_shows_where_left_out_topics_land():
    rubrics = {
        "A": {"topics": ["red apples", "green apples", "fruit trees"]},
        "B": {"topics": ["fast cars", "red cars"]},
    }
    vectors = {code: [models._unit(vector(t)) for t in r["topics"]] for code, r in rubrics.items()}
    found = areas.confusion(rubrics, vectors, 1)
    assert found["A"] == {"A": 3}  # "fruit trees" shares no word: a tie, and A comes first
    assert found["B"] == {"B": 1, "A": 1}  # "red cars" is as near to "red apples" as to "fast cars"
    assert areas.similarity([1.0, 0.0], [[0.6, 0.8], [0.8, 0.6], [0.0, 1.0]], 2) == 0.7


def test_rubrics_check_embeds_the_public_topics_and_reports_confusion(monkeypatch, capsys):
    endpoint = FakeEndpoint(monkeypatch)
    monkeypatch.setattr(areas, "DIR_RUBRICS_DEFAULT", core.DIR_DATA / "none")
    for rubric in areas.parse(PAGE, "https://example.org/call"):
        areas.save(rubric, core.DIR_RUBRICS)
    cli.main(["--embeddings-model", "m", "rubrics", "check"])
    out = capsys.readouterr().out
    assert "LEARN  2/2 own" in out and "ROBOT  0/1 own; LEARN 1" in out
    assert endpoint.requests[0]["model"] == "m"
    cli.main(["--embeddings-model", "m", "--cache-only", "rubrics", "check"])
    assert len(endpoint.requests) == 1
    with pytest.raises(SystemExit, match="Embeddings: .* not embedded with n"):
        cli.main(["--embeddings-model", "n", "--cache-only", "rubrics", "check"])


def test_every_connection_for_paper_data_must_reach_the_allowed_networks(monkeypatch):
    from urllib3.connection import HTTPConnection, HTTPSConnection

    reached = {"address": "127.0.0.1"}

    class Socket:
        def getpeername(self):
            return (reached["address"], 11434)

        def close(self):
            pass

    def connect(self):  # instead of opening a socket: one that reached `reached`
        self.sock = Socket()

    monkeypatch.setattr(HTTPConnection, "connect", connect)
    monkeypatch.setattr(HTTPSConnection, "connect", connect)
    s = models.settings(CONFIG)
    pools = models.session(s, private=True).get_adapter("http://x").poolmanager
    for scheme in ("http", "https"):
        connection = pools.pool_classes_by_scheme[scheme].ConnectionCls("localhost")
        connection.connect()  # loopback: allowed
        reached["address"] = "93.184.216.34"  # e.g. DNS answered differently, or a proxy
        with pytest.raises(models.NotLocal, match="connected to 93.184.216.34"):
            connection.connect()
        reached["address"] = "127.0.0.1"
    public = models.session(s).get_adapter("http://x").poolmanager
    assert public.pool_classes_by_scheme["http"] is not pools.pool_classes_by_scheme["http"]


def test_paper_data_follows_no_redirect_and_no_proxy_from_the_environment(monkeypatch, tmp_path):
    endpoint, s = FakeEndpoint(monkeypatch), models.settings(CONFIG)
    resolves_to(monkeypatch, "127.0.0.1")
    models.embed(s, ["public topic"], tmp_path, private=False)
    models.embed(s, ["an abstract"], tmp_path, private=True)
    public, private = endpoint.requests
    assert public["redirects"] and public["proxies from the environment"]
    assert not private["redirects"] and not private["proxies from the environment"]

    def redirected(*args, **kwargs):
        class Response:
            is_redirect = True

        return Response()

    monkeypatch.setattr(requests.Session, "post", redirected)
    with pytest.raises(PermissionError, match="redirects elsewhere"):
        models.embed(s, ["another abstract"], tmp_path, private=True)
