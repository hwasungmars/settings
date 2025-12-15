#!/usr/bin/env python3

"""Deploy Helix configs."""

import argparse
import json
import logging
import pathlib
import subprocess

LOGGER = logging.getLogger(__name__)
SCRIPT_DIR = pathlib.Path(__file__).parent


def main(args: argparse.Namespace) -> None:
    """Main function."""
    LOGGER.info("Running with args: %s", json.dumps(dict(vars(args)), indent=2))
    _ = subprocess.run(["uv", "tool", "install", "basedpyright"], check=True)
    _ = subprocess.run(["uv", "tool", "install", "ruff"], check=True)
    _ = subprocess.run(["uv", "tool", "install", "ty"], check=True)
    target_config_dir = pathlib.Path.home() / ".config" / "helix"
    assert not target_config_dir.exists(), f"{target_config_dir} is not empty."
    source_config_dir = SCRIPT_DIR / "dot_config"
    LOGGER.info("Linking %s -> %s", source_config_dir, target_config_dir)
    target_config_dir.symlink_to(source_config_dir)


def arg_parse() -> argparse.Namespace:
    """Parse arguments and return an args object."""
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument(
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
