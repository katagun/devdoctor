from __future__ import annotations

from diskdoctor.providers.base import Provider


def test_provider_details_defaults_to_none():
    """Subclasses inherit None unless they override."""

    class _Stub(Provider):
        name = "stub"
        description = "x"
        platforms = ("darwin",)
        risk = None  # type: ignore[assignment]

        def discover(self):
            return []

    assert _Stub.details is None
