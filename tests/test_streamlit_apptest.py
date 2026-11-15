# -*- coding: utf-8 -*-
"""Streamlit AppTest smoke test; skipped when Streamlit is unavailable."""
from __future__ import annotations

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest


def test_app_renders_without_backend() -> None:
    app = AppTest.from_file("streamlit_app.py", default_timeout=15)
    app.run()
    # With no backend the page must show an error and stop gracefully,
    # never raise an unhandled exception or open a Tk window.
    assert not app.exception
    assert len(app.error) >= 1
