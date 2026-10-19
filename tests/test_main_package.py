import subprocess
import sys

from aamas_review_monitor import __version__
from aamas_review_monitor.greeting import greet
from aamas_review_monitor.resources import DIR_RESOURCES, FILE_CONFIG, FILE_GREETING


def test_version_comes_from_package_metadata():
    assert __version__.count(".") == 2


def test_resources_exist():
    assert DIR_RESOURCES.is_dir()
    assert FILE_CONFIG.is_file() and FILE_GREETING.is_file()


def test_greet():
    assert greet("Ada") == "Dear Ada, the package says: Hello World"
    assert greet() == "Dear stranger, the package says: Hello World"


def test_run_as_module():
    out = subprocess.run(
        [sys.executable, "-m", "aamas_review_monitor", "Ada"], check=True, capture_output=True, text=True
    )
    assert out.stdout.strip() == greet("Ada")
