#!/usr/bin/env bash
# -*- coding: utf8 -*-

# Author: Hwasung Lee

set -eux

script_dir=$(cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd)

ruff format
ruff check --fix
ty check
