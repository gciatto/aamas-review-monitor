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

from aamas_review_monitor.core import LoggedRetry

PRESETS = {
    "ollama": {"url": "http://localhost:11434/v1", "model": "bge-m3"},
    "openai": {"url": "https://api.openai.com/v1", "model": "text-embedding-3-small"},
}
BATCH = 32  # texts per request
DUMPER = getattr(yaml, "CSafeDumper", yaml.SafeDumper)
LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


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
    allowed = [ipaddress.ip_network(n) for n in networks]
    # ponytail: requests resolves the host again; a DNS answer changing in between would slip by
    outside = sorted(
        a for a in found if not any(ipaddress.ip_address(a.split("%")[0]) in n for n in allowed)
    )
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


def session(s: Settings) -> requests.Session:
    """Retries with exponential backoff and jitter on rate limits, server errors and connection
    failures, honouring Retry-After (a repeated embedding request does no harm)."""
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
    for prefix in ("https://", "http://"):
        result.mount(prefix, HTTPAdapter(max_retries=retry))
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
    `cache_only`: LookupError instead of asking the endpoint."""
    files = [directory / f"{fingerprint(s.model, t)}.yaml" for t in texts]
    missing = list(dict.fromkeys(t for t, f in zip(texts, files) if not f.is_file()))
    if missing and cache_only:
        raise LookupError(f"{len(missing)} texts not embedded with {s.model} yet (cache only)")
    if missing:
        if private:
            check_local(s.url, s.networks)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        client = session(s)
        for start in range(0, len(missing), BATCH):
            batch = missing[start : start + BATCH]
            response = client.post(
                f"{s.url.rstrip('/')}/embeddings",
                json={"model": s.model, "input": batch},
                timeout=300,
            )
            response.raise_for_status()
            for text, item in zip(batch, sorted(response.json()["data"], key=lambda d: d["index"])):
                file = directory / f"{fingerprint(s.model, text)}.yaml"
                cached = {"model": s.model, "input": text, "embedding": item["embedding"]}
                file.write_text(yaml.dump(cached, Dumper=DUMPER), encoding="utf-8")
                file.chmod(0o600)  # may hold paper text
    return [_unit(yaml.load(f.read_text(encoding="utf-8"), LOADER)["embedding"]) for f in files]
