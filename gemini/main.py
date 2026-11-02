#!/usr/bin/env python3

"""Deploy Gemini and Antigravity configs."""

from __future__ import annotations

import argparse
import logging
import pathlib
import shutil

LOGGER = logging.getLogger(__name__)
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent


def main(args: argparse.Namespace) -> None:
    """Main function."""
    _ = args
    config_dir = pathlib.Path.home() / ".gemini" / "config"
    rules_dir = config_dir / "rules"
    plugins_dir = config_dir / "plugins"
    rules_dir.mkdir(parents=True, exist_ok=True)
    plugins_dir.mkdir(parents=True, exist_ok=True)

    force_symlink_to(config_dir / "GEMINI.md", SCRIPT_DIR / "data" / "GEMINI.md")
    force_symlink_to(
        rules_dir / "uk-spelling.md",
        SCRIPT_DIR / "data" / "rules" / "uk-spelling.md",
    )
    force_symlink_to(
        plugins_dir / "triage-gmail",
        SCRIPT_DIR / "data" / "plugins" / "triage-gmail",
    )


def force_symlink_to(source: pathlib.Path, target: pathlib.Path) -> None:
    """Create or replace a symlink at source pointing to target."""
    if source.is_symlink() or source.is_file():
        source.unlink()
    elif source.is_dir():
        shutil.rmtree(source)

    LOGGER.info("Linking %s -> %s", source, target)
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
