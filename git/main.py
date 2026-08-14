#!/usr/bin/env python3

"""Deploy git configs."""

import argparse
import logging
import pathlib

LOGGER = logging.getLogger(__name__)
SCRIPT_DIR = pathlib.Path(__file__).parent
LOCAL_CONFIG_HEADER = """\
# Machine specific git settings, deliberately untracked.
#
# ~/.gitconfig includes this file last, so anything here overrides the tracked config. Put values
# that only make sense on this machine in here: absolute paths, per-host credentials, [maintenance]
# repo lists.
"""


def main(args: argparse.Namespace) -> None:
    """Main function."""
    force_symlink_to(pathlib.Path.home() / ".gitconfig", SCRIPT_DIR / "data" / "dot_gitconfig")
    force_symlink_to(pathlib.Path.home() / ".gitignore", SCRIPT_DIR / "data" / "dot_gitignore")
    force_symlink_to(
        pathlib.Path.home() / ".local" / "bin" / "git-pr",
        SCRIPT_DIR / "data" / "git-pr",
    )
    force_symlink_to(
        pathlib.Path.home() / ".local" / "bin" / "git-default-branch",
        SCRIPT_DIR / "data" / "git-default-branch",
    )
    seed_local_config(pathlib.Path.home() / ".gitconfig.local")


def seed_local_config(target: pathlib.Path) -> None:
    """Create the untracked machine local config, leaving an existing one alone."""
    if target.exists():
        LOGGER.info("Leaving existing %s alone.", target)
        return

    LOGGER.info("Seeding %s", target)
    _ = target.write_text(LOCAL_CONFIG_HEADER)


def force_symlink_to(source: pathlib.Path, target: pathlib.Path) -> None:
    if source.is_symlink() or source.exists():
        source.unlink()

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
