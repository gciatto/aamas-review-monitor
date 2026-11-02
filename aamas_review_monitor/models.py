"""Embeddings from an OpenAI-compatible endpoint (Ollama or OpenAI), cached per model and text.
Paper data only goes to endpoints that resolve inside the allowed networks; public text (the
areas' topics) may go anywhere."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import socket
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import urlsplit

import requests
import yaml
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

from aamas_review_monitor.core import LoggedRetry

PRESETS = {
    "ollama": {"url": "http://localhost:11434/v1", "model": "nomic-embed-text"},
    "openai": {"url": "https://api.openai.com/v1", "model": "text-embedding-3-small"},
}
BATCH = 32  # texts per request
DUMPER = getattr(yaml, "CSafeDumper", yaml.SafeDumper)
LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


class NotEmbedded(LookupError):
    """Texts missing from the cache when only the cache may be used."""


class NotLocal(Exception):
    """A connection for paper data reached an address outside the allowed networks. Not an
    OSError, so that urllib3 lets it through instead of retrying."""


def allowed(address: str, networks: tuple[str, ...]) -> bool:
    ip = ipaddress.ip_address(address.split("%")[0])  # an IPv6 address may carry a zone
    return any(ip in ipaddress.ip_network(n) for n in networks)


class Settings(NamedTuple):
    vendor: str
    url: str
    model: str
    api_key: str
    networks: tuple[str, ...]
    retries: int
    backoff_seconds: float
    backoff_max_seconds: float


def settings(config: dict, **given: object) -> Settings:
    """Each setting from, first found: `given` (command line or UI), the environment
    (AAMAS_MONITOR_EMBEDDINGS_<NAME>), the config (embeddings_<name>), the vendor's preset. The
    API key is never read from the config. ValueError on an unknown vendor or a bad network."""

    def pick(name: str) -> Any:
        key = f"embeddings_{name}"
        if given.get(name) is not None:
            return given[name]
        if (value := os.environ.get(f"AAMAS_MONITOR_{key.upper()}")) is not None:
            return value
        return config.get(key) if name != "api_key" else None

    vendor = str(pick("vendor"))
    if vendor not in PRESETS:
        raise ValueError(f"embeddings vendor {vendor!r} is not one of {', '.join(PRESETS)}")
    networks = pick("networks") or []
    if isinstance(networks, str):
        networks = networks.split(",")
    networks = tuple(n.strip() for n in networks if n.strip())
    for network in networks:
        ipaddress.ip_network(network)  # ValueError on a typo
    return Settings(
        vendor,
        str(pick("url") or PRESETS[vendor]["url"]),
        str(pick("model") or PRESETS[vendor]["model"]),
        str(pick("api_key") or ""),
        networks,
        int(pick("retries")),
        float(pick("backoff_seconds")),
        float(pick("backoff_max_seconds")),
    )


def check_local(url: str, networks: tuple[str, ...]) -> None:
    """PermissionError unless every address the endpoint's host resolves to is in `networks`."""
    host = urlsplit(url).hostname or ""
    try:
        found = {str(info[4][0]) for info in socket.getaddrinfo(host, None)}
    except socket.gaierror as e:
        raise PermissionError(f"cannot resolve {host}: {e}") from None
    # a first check, for a clear error before connecting; `session` checks every connection
    outside = sorted(a for a in found if not allowed(a, networks))
    if outside:
        raise PermissionError(
            f"{host} resolves to {', '.join(outside)}, outside the allowed networks "
            f"({', '.join(networks) or 'none'}): paper data only goes to local endpoints "
            "(--embeddings-networks, AAMAS_MONITOR_EMBEDDINGS_NETWORKS)"
        )


def fingerprint(model: str, text: str) -> str:
    """sha512 of the request for one text: names its cached response."""
    request = json.dumps({"model": model, "input": text}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha512(request.encode()).hexdigest()


def _local(networks: tuple[str, ...]) -> type[HTTPAdapter]:
    """An adapter whose every connection checks the address it reached before anything is sent
    on it: a DNS answer changing after `check_local`, a proxy or a redirect cannot take paper
    data outside `networks`."""

    def checked(base: Any) -> type:
        def connect(self: Any) -> None:
            base.connect(self)
            address = str(self.sock.getpeername()[0])
            if not allowed(address, networks):
                self.close()
                raise NotLocal(f"connected to {address}, outside {', '.join(networks)}")

        return type(f"Local{base.__name__}", (base,), {"connect": connect})

    pools = {
        "http": type(
            "LocalHTTPPool", (HTTPConnectionPool,), {"ConnectionCls": checked(HTTPConnection)}
        ),
        "https": type(
            "LocalHTTPSPool", (HTTPSConnectionPool,), {"ConnectionCls": checked(HTTPSConnection)}
        ),
    }

    class Adapter(HTTPAdapter):
        def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
            super().init_poolmanager(*args, **kwargs)
            self.poolmanager.pool_classes_by_scheme = pools

    return Adapter


def session(s: Settings, private: bool = False) -> requests.Session:
    """Retries with exponential backoff and jitter on rate limits, server errors and connection
    failures, honouring Retry-After (a repeated embedding request does no harm). `private`: for
    paper data, every connection must reach the allowed networks, and no proxy from the
    environment is used."""
    retry = LoggedRetry(
        total=s.retries,
        connect=s.retries,
        backoff_factor=s.backoff_seconds,
        backoff_max=s.backoff_max_seconds,
        backoff_jitter=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=None,
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    result = requests.Session()
    adapter: type[HTTPAdapter] = _local(s.networks) if private else HTTPAdapter
    for prefix in ("https://", "http://"):
        result.mount(prefix, adapter(max_retries=retry))
    result.trust_env = not private  # no HTTP(S)_PROXY, .netrc or such for paper data
    if s.api_key:
        result.headers["Authorization"] = f"Bearer {s.api_key}"
    return result


def _unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


def embed(
    s: Settings, texts: list[str], directory: Path, private: bool, cache_only: bool = False
) -> list[list[float]]:
    """Unit vectors of `texts`, from the cache in `directory` or else the endpoint. `private`:
    the texts hold paper data, so the endpoint must be local (PermissionError otherwise).
    `cache_only`: NotEmbedded instead of asking the endpoint."""
    files = [directory / f"{fingerprint(s.model, t)}.yaml" for t in texts]
    missing = list(dict.fromkeys(t for t, f in zip(texts, files) if not f.is_file()))
    if missing and cache_only:
        raise NotEmbedded(f"{len(missing)} texts not embedded with {s.model} yet (cache only)")
    if missing:
        if private:
            check_local(s.url, s.networks)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        client = session(s, private)
        for start in range(0, len(missing), BATCH):
            batch = missing[start : start + BATCH]
            try:
                response = client.post(
                    f"{s.url.rstrip('/')}/embeddings",
                    json={"model": s.model, "input": batch},
                    timeout=300,
                    allow_redirects=not private,  # a redirect could lead outside the networks
                )
            except NotLocal as e:
                raise PermissionError(f"paper data only goes to local endpoints: {e}") from None
            if response.is_redirect:
                raise PermissionError(f"{s.url} redirects elsewhere: paper data not sent there")
            response.raise_for_status()
            for text, item in zip(batch, sorted(response.json()["data"], key=lambda d: d["index"])):
                file = directory / f"{fingerprint(s.model, text)}.yaml"
                cached = {"model": s.model, "input": text, "embedding": item["embedding"]}
                file.write_text(yaml.dump(cached, Dumper=DUMPER), encoding="utf-8")
                file.chmod(0o600)  # may hold paper text
    return [_unit(yaml.load(f.read_text(encoding="utf-8"), LOADER)["embedding"]) for f in files]
