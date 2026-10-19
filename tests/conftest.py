import pytest


@pytest.fixture(autouse=True)
def no_openreview(monkeypatch):
    """Tests never reach OpenReview: no real logins, downloads or emails."""
    import openreview  # type: ignore[import-untyped]

    def refuse(*args, **kwargs):
        raise AssertionError("tests must use a fake client")

    monkeypatch.setattr(openreview.api, "OpenReviewClient", refuse)


@pytest.fixture(autouse=True)
def private_data(tmp_path_factory, monkeypatch):
    """Tests never touch the real data folder (snapshots, papers, token, history)."""
    from aamas_review_monitor import __main__ as cli

    data = tmp_path_factory.mktemp("data")
    monkeypatch.setattr(cli, "DIR_DATA", data)
    monkeypatch.setattr(cli, "DIR_SNAPSHOTS", data / "snapshots")
    monkeypatch.setattr(cli, "DIR_PAPERS", data / "papers")
    monkeypatch.setattr(cli, "FILE_TOKEN", data / "token")
    monkeypatch.setattr(cli, "FILE_HISTORY", data / "history.jsonl")
