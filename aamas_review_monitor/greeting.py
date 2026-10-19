import json

from aamas_review_monitor.model import MyClass
from aamas_review_monitor.resources import FILE_CONFIG, FILE_GREETING


def greet(name: str | None = None) -> str:
    config = json.loads(FILE_CONFIG.read_text(encoding="utf-8"))
    template = FILE_GREETING.read_text(encoding="utf-8").strip()
    return template.format(name=name or config["default_name"], message=MyClass().my_method())
