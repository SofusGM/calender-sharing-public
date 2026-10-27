from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class MissingCredentials(KeyError):
    pass


def require_env(name: str, env=os.environ) -> str:
    # GitHub sætter en manglende secret til en tom streng, ikke til ingenting.
    value = env.get(name)
    if not value:
        raise MissingCredentials(f"Miljøvariablen {name} mangler (se README.md).")
    return value


def expand_env(value, env=os.environ):
    """Erstatter ${NAVN} med miljøvariablen NAVN, så private værdier
    (fx navne) kan holdes ude af repoet."""
    if isinstance(value, dict):
        return {k: expand_env(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(v, env) for v in value]
    if isinstance(value, str):
        def replace(match):
            name = match.group(1)
            if not env.get(name):
                raise KeyError(f"Miljøvariablen {name} mangler (bruges i config.yaml).")
            return env[name]
        return _VAR.sub(replace, value)
    return value


def load_config(path: str | Path) -> dict:
    return expand_env(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
