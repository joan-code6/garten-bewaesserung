#!/usr/bin/env python3
"""Configuration loader — reads config.yaml."""

import os
import yaml

CONFIG_PATH = os.environ.get(
    "GARDEN_CONFIG",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml"),
)


def _load():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(
            f"Config not found at {CONFIG_PATH}. Copy config.example.yaml to config.yaml"
        )
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


_cfg = _load()


def get(*keys, default=None):
    """Get a nested key from config, e.g. get('broker', 'host')."""
    node = _cfg
    for k in keys:
        if isinstance(node, dict):
            node = node.get(k)
        else:
            return default
        if node is None:
            return default
    return node


def reload():
    """Reload config from disk (useful for hot-reload)."""
    global _cfg
    _cfg = _load()
