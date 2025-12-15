#!/usr/bin/env python3

"""Describe what this package does."""

import argparse
import json
import logging
import pathlib

LOGGER = logging.getLogger(__name__)
SCRIPT_DIR = pathlib.Path(__file__).parent


def main(args: argparse.Namespace) -> None:
    """Main function."""
    LOGGER.info("Running with args: %s", json.dumps(dict(vars(args)), indent=2))


def arg_parse() -> argparse.Namespace:
    """Parse arguments and return an args object."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log-level",
        dest="log_level",
        choices=logging._nameToLevel.keys(),
        default="INFO",
        help="Log level for the default logger.",
    )

    return parser.parse_args()


if __name__ == "__main__":
    ARGS = arg_parse()
    logging.basicConfig(
        level=logging._nameToLevel[ARGS.log_level],
        format=("%(asctime)s " + logging.BASIC_FORMAT),
    )
    main(ARGS)
