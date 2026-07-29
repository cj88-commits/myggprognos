"""Adds forecast/src to sys.path so top-level scripts can import the
forecast package without it being pip-installed."""
import sys
from pathlib import Path

FORECAST_SRC = Path(__file__).resolve().parents[1] / "forecast" / "src"
if str(FORECAST_SRC) not in sys.path:
    sys.path.insert(0, str(FORECAST_SRC))
