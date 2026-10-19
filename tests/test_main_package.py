import subprocess
import sys

from main_package import __version__
from main_package.greeting import greet
from main_package.resources import DIR_RESOURCES, FILE_CONFIG, FILE_GREETING


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
        [sys.executable, "-m", "main_package", "Ada"], check=True, capture_output=True, text=True
    )
    assert out.stdout.strip() == greet("Ada")
