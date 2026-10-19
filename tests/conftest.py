import pytest


@pytest.fixture(autouse=True)
def no_openreview(monkeypatch):
    """Tests never reach OpenReview: no real logins, downloads or emails."""
    import openreview  # type: ignore[import-untyped]

    def refuse(*args, **kwargs):
        raise AssertionError("tests must use a fake client")

    monkeypatch.setattr(openreview.api, "OpenReviewClient", refuse)
