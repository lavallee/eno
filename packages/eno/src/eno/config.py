import os
from pathlib import Path


class VaultNotConfigured(RuntimeError):
    """Raised when no vault path was given via --vault or $ENO_VAULT_DIR."""


def vault_dir(override: str | Path | None = None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    env = os.environ.get("ENO_VAULT_DIR")
    if env:
        return Path(env).expanduser().resolve()
    raise VaultNotConfigured(
        "No vault configured. Pass --vault PATH or set $ENO_VAULT_DIR to the "
        "root of your Obsidian vault."
    )


def eno_dir(vault: Path) -> Path:
    env = os.environ.get("ENO_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return vault / ".eno"


def index_path(vault: Path) -> Path:
    return eno_dir(vault) / "index.db"


def state_path(vault: Path) -> Path:
    return eno_dir(vault) / "state.json"
