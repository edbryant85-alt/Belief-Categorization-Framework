from __future__ import annotations

from pathlib import Path
from typing import Any


class SourceRegistrationError(ValueError):
    pass


def validate_source_file(source_path: str | Path, config: dict[str, Any]) -> Path:
    path = Path(source_path)
    if not path.exists():
        raise SourceRegistrationError(f"Source file not found: {path}")
    if not path.is_file():
        raise SourceRegistrationError(f"Source path is not a file: {path}")

    supported_extensions = {
        extension.lower() for extension in config["sources"]["supported_extensions"]
    }
    if path.suffix.lower() not in supported_extensions:
        allowed = ", ".join(sorted(supported_extensions))
        raise SourceRegistrationError(
            f"Unsupported source file extension '{path.suffix}'. Supported extensions: {allowed}"
        )
    return path


def title_from_filename(source_path: str | Path) -> str:
    return Path(source_path).stem.replace("_", " ").replace("-", " ").strip().title()


def read_source_text(source_path: str | Path) -> str:
    return Path(source_path).read_text(encoding="utf-8")
