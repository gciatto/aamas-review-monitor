import logging
from importlib.metadata import version

__version__ = version("template-python-project-uv")  # pyproject.toml is the only source

logger = logging.getLogger("main_package")
