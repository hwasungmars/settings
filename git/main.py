#!/usr/bin/env python3

"""Deploy Helix configs."""

import argparse
import logging
import pathlib

LOGGER = logging.getLogger(__name__)
SCRIPT_DIR = pathlib.Path(__file__).parent


def main(args: argparse.Namespace) -> None:
    """Main function."""
    force_symlink_to(pathlib.Path.home() / ".gitconfig", SCRIPT_DIR / "data" / "dot_gitconfig")
    force_symlink_to(pathlib.Path.home() / ".gitignore", SCRIPT_DIR / "data" / "dot_gitignore")
    force_symlink_to(pathlib.Path.home() / ".local" / "bin" / "git-pr", SCRIPT_DIR / "data" / "git-pr")


def force_symlink_to(source: pathlib.Path, target: pathlib.Path) -> None:
    if target.is_symlink():
        target.unlink()

    source.symlink_to(target)
        


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
