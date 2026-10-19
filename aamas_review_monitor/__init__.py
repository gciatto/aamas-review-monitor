import logging
from importlib.metadata import version

__version__ = version("aamas-review-monitor")  # pyproject.toml is the only source

logger = logging.getLogger("aamas_review_monitor")
