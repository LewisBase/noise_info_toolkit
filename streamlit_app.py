# -*- coding: utf-8 -*-
"""Compatibility entrypoint for the field Streamlit UI.

The legacy implementation is preserved in git history/tag
``v1.1.0-field-baseline``.  The field UI has no Tk/filedialog and uses the
versioned API.
"""
from app.web.streamlit_app import main

main()
