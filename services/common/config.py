"""Utility helpers for loading YAML configuration with environment overrides."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml


@dataclass
class ConfigLoader:
    """Loads configuration files and expands environment variables."""

    base_dir: Path

    def load(self, relative_path: str) -> Dict[str, Any]:
        path = self.base_dir / relative_path
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return self._expand_env(data)

    def _expand_env(self, node: Any) -> Any:
        if isinstance(node, dict):
            return {key: self._expand_env(value) for key, value in node.items()}
        if isinstance(node, list):
            return [self._expand_env(item) for item in node]
        if isinstance(node, str):
            return os.path.expandvars(node)
        return node


def load_config(relative_path: str) -> Dict[str, Any]:
    """Convenience wrapper that assumes the repository root as base directory."""

    base = Path(__file__).resolve().parents[2]
    loader = ConfigLoader(base)
    return loader.load(relative_path)
