#!/usr/bin/env python3

"""Deploy zsh configs."""

import argparse
import logging
import pathlib

LOGGER = logging.getLogger(__name__)
SCRIPT_DIR = pathlib.Path(__file__).parent


def main(args: argparse.Namespace) -> None:
    """Main function."""
    custom_dir = pathlib.Path.home() / ".oh-my-zsh" / "custom"
    if not custom_dir.is_dir():
        raise SystemExit(
            f"{custom_dir} does not exist. Install Oh My Zsh first: it owns ~/.zshrc and sources "
            "every *.zsh in that directory, which is how this config gets loaded."
        )

    force_symlink_to(custom_dir / "settings.zsh", SCRIPT_DIR / "data" / "settings.zsh")


def force_symlink_to(source: pathlib.Path, target: pathlib.Path) -> None:
    if source.is_symlink() or source.exists():
        source.unlink()

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
