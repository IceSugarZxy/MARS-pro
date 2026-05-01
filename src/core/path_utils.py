# -*- coding: utf-8 -*-
"""
Runtime path helpers.
"""

import os
import sys


def get_runtime_root() -> str:
    """Return the application root for both source and frozen runs."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_project_root() -> str:
    """Return the project root when running from source, or exe dir when frozen."""
    if getattr(sys, "frozen", False):
        return get_runtime_root()
    return os.path.dirname(get_runtime_root())


def get_config_path(config_file: str = "configuration.txt") -> str:
    """Build a path for runtime configuration storage."""
    return os.path.join(get_runtime_root(), config_file)


def get_data_dir(*parts: str) -> str:
    """Build a path under the runtime data directory."""
    return os.path.join(get_project_root(), "data", *parts)
