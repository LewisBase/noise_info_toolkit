# -*- coding: utf-8 -*-
"""Import-only smoke test; skipped when Streamlit is not installed."""
from __future__ import annotations

import pytest

pytest.importorskip("streamlit")


def test_streamlit_module_imports() -> None:
    import app.web.streamlit_app as ui
    assert callable(ui.main)
