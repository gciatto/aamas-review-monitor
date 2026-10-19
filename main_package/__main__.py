import logging
import sys

from main_package.greeting import greet


def main() -> None:
    # Only the application configures logging; importing the package leaves it alone.
    logging.basicConfig(level=logging.DEBUG)
    print(greet(*sys.argv[1:2]))


if __name__ == "__main__":
    main()
