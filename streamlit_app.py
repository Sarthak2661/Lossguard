"""Canonical Streamlit entrypoint for the LossGuard dashboard."""

from pathlib import Path
from runpy import run_path

# Execute the UI script on every Streamlit rerun. A normal module import would
# stay in sys.modules and could leave the page showing stale code or no content.
run_path(str(Path(__file__).parent / "apps" / "dashboard" / "app.py"))
