from __future__ import annotations

import hashlib
import mimetypes
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SUPPORTED_TEXT_EXTENSIONS = {".md", ".txt", ".json", ".jsonl", ".csv", ".html", ".htm"}
METADATA_ONLY_EXTENSIONS = {".pdf", ".docx"}
UNSUPPORTED_EXTENSIONS = {
    ".7z",
    ".bmp",
    ".gif",
    ".gz",
    ".jpeg",
    ".jpg",
    ".mp3",
    ".mp4",
    ".png",
    ".tar",
    ".wav",
    ".webp",
    ".xlsx",
    ".zip",
}
PROPHECY_MARKERS = ("prophecy", "prophecies", "prophetic")
TEMP_PREFIXES = ("~$", ".~", ".DS_Store")


@dataclass(frozen=True)
class ArchiveScanLimits:
    max_sources: int | None = None
    max_depth: int = 10
    max_files: int = 5000
    large_file_threshold_mb: int = 25
    hash_threshold_mb: int = 10


@dataclass(frozen=True)
class ArchiveScanResult:
    candidates: list[dict[str, Any]]
    unsupported_files: list[dict[str, Any]]
    prophecy_exclusions: list[dict[str, Any]]
    warnings: list[str]
    errors: list[str]
    truncated_by_max_files: bool = False
    truncated_by_max_sources: bool = False
    truncated_by_depth: bool = False


def scan_archive_root(
    archive_root: str | Path,
    *,
    corpus: str,
    limits: ArchiveScanLimits,
) -> ArchiveScanResult:
    root = Path(archive_root).expanduser()
    warnings: list[str] = []
    errors: list[str] = []
    candidates: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    truncated_by_max_files = False
    truncated_by_max_sources = False
    truncated_by_depth = False

    if not root.exists():
        return ArchiveScanResult(
            candidates=[],
            unsupported_files=[],
            prophecy_exclusions=[],
            warnings=[f"Archive root does not exist: {root}"],
            errors=[],
        )
    if not root.is_dir():
        return ArchiveScanResult(
            candidates=[],
            unsupported_files=[],
            prophecy_exclusions=[],
            warnings=[],
            errors=[f"Archive root is not a directory: {root}"],
        )

    seen_files = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = _safe_relative(root, path)
        depth = len(Path(relative).parts) - 1
        if depth > limits.max_depth:
            truncated_by_depth = True
            continue
        if _is_temp_or_system(path):
            continue
        seen_files += 1
        if seen_files > limits.max_files:
            truncated_by_max_files = True
            break
        if is_prophecy_text(f"{relative} {path.name}"):
            exclusions.append(_excluded_record(root, path, corpus=corpus))
            continue

        extension = path.suffix.lower()
        if extension in SUPPORTED_TEXT_EXTENSIONS or extension in METADATA_ONLY_EXTENSIONS:
            candidates.append(_candidate_record(root, path, corpus=corpus, limits=limits))
            if limits.max_sources is not None and len(candidates) >= limits.max_sources:
                truncated_by_max_sources = True
                break
        else:
            unsupported.append(_unsupported_record(root, path, corpus=corpus))

    if truncated_by_depth:
        warnings.append(f"Some files were skipped because they were deeper than max_depth={limits.max_depth}.")
    if truncated_by_max_files:
        warnings.append(f"Archive scan stopped after max_files={limits.max_files}.")
    if truncated_by_max_sources:
        warnings.append(f"Candidate scan stopped after max_sources={limits.max_sources}.")

    return ArchiveScanResult(
        candidates=candidates,
        unsupported_files=unsupported,
        prophecy_exclusions=exclusions,
        warnings=warnings,
        errors=errors,
        truncated_by_max_files=truncated_by_max_files,
        truncated_by_max_sources=truncated_by_max_sources,
        truncated_by_depth=truncated_by_depth,
    )


def is_prophecy_text(value: str) -> bool:
    text = value.lower()
    return any(marker in text for marker in PROPHECY_MARKERS)


def _candidate_record(root: Path, path: Path, *, corpus: str, limits: ArchiveScanLimits) -> dict[str, Any]:
    stat = path.stat()
    extension = path.suffix.lower()
    size_bytes = stat.st_size
    large_threshold = limits.large_file_threshold_mb * 1024 * 1024
    hash_threshold = limits.hash_threshold_mb * 1024 * 1024
    is_supported_text = extension in SUPPORTED_TEXT_EXTENSIONS and size_bytes <= large_threshold
    is_large_file = size_bytes > large_threshold
    is_metadata_only = extension in METADATA_ONLY_EXTENSIONS or is_large_file
    sha256 = ""
    hash_status = "skipped_large_file" if size_bytes > hash_threshold else "not_computed"
    if size_bytes <= hash_threshold:
        sha256 = _sha256(path)
        hash_status = "computed"
    content_status = "metadata_only_large_file" if is_large_file else "metadata_only_format" if extension in METADATA_ONLY_EXTENSIONS else "supported_text_metadata_only"
    relative = _safe_relative(root, path)
    title = _detect_title(path)
    source_type = _detect_source_type(path)
    return {
        "candidate_id": _candidate_id(relative),
        "corpus": corpus,
        "name": path.name,
        "relative_path": relative,
        "absolute_path_or_archive_uri": str(path.resolve()),
        "file_extension": extension,
        "mime_type_or_inferred_type": mimetypes.guess_type(path.name)[0] or _inferred_type(extension),
        "size_bytes": size_bytes,
        "modified_time": _iso_time(stat.st_mtime),
        "created_time": _iso_time(getattr(stat, "st_ctime", 0)),
        "sha256": sha256,
        "hash_status": hash_status,
        "content_status": content_status,
        "is_supported_text": is_supported_text,
        "is_metadata_only": is_metadata_only,
        "is_large_file": is_large_file,
        "is_prophecy_excluded": False,
        "detected_source_type": source_type,
        "detected_title": title,
        "detected_author": _detect_author(path),
        "detected_date": _detect_date(path.name),
        "registered_match_status": "unchecked",
        "registered_source_id": "",
        "registered_match_reason": "",
        "cluster_suggestion": _cluster_suggestion(corpus, path),
        "source_role_suggestion": _role_suggestion(source_type),
        "recommended_action": "needs human review before registration",
        "duplicate_risk": "unknown",
        "priority_suggestion": "normal",
        "recommended_next_action": "review candidate metadata; register manually if selected",
        "warnings": "",
    }


def _unsupported_record(root: Path, path: Path, *, corpus: str) -> dict[str, Any]:
    stat = path.stat()
    return {
        "corpus": corpus,
        "name": path.name,
        "relative_path": _safe_relative(root, path),
        "absolute_path_or_archive_uri": str(path.resolve()),
        "file_extension": path.suffix.lower(),
        "mime_type_or_inferred_type": mimetypes.guess_type(path.name)[0] or "unsupported",
        "size_bytes": stat.st_size,
        "modified_time": _iso_time(stat.st_mtime),
        "reason": "unsupported_file_type",
    }


def _excluded_record(root: Path, path: Path, *, corpus: str) -> dict[str, Any]:
    stat = path.stat()
    return {
        "corpus": corpus,
        "name": path.name,
        "relative_path": _safe_relative(root, path),
        "absolute_path_or_archive_uri": str(path.resolve()),
        "file_extension": path.suffix.lower(),
        "size_bytes": stat.st_size,
        "reason": "prophecy_excluded",
    }


def _safe_relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _candidate_id(relative_path: str) -> str:
    digest = hashlib.sha1(relative_path.encode("utf-8")).hexdigest()[:12]
    return f"CAND-{digest}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iso_time(timestamp: float) -> str:
    if not timestamp:
        return ""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(timespec="seconds")


def _inferred_type(extension: str) -> str:
    if extension in SUPPORTED_TEXT_EXTENSIONS:
        return "text/source"
    if extension in METADATA_ONLY_EXTENSIONS:
        return "document/metadata-only"
    if extension in UNSUPPORTED_EXTENSIONS:
        return "unsupported"
    return "unknown"


def _is_temp_or_system(path: Path) -> bool:
    return path.name in TEMP_PREFIXES or any(path.name.startswith(prefix) for prefix in TEMP_PREFIXES)


def _detect_source_type(path: Path) -> str:
    text = path.as_posix().lower()
    name = path.name.lower()
    if "watch" in text and path.suffix.lower() == ".json":
        return "watch_history"
    if "youtube" in text or "transcript" in text or "yt" in name:
        return "youtube_transcript"
    if "sermon" in text or "mosaic" in text:
        return "sermon_transcript"
    if "packet" in text:
        return "packet"
    if "manifest" in text:
        return "manifest"
    if "book" in text or path.suffix.lower() in {".pdf", ".docx"}:
        return "book_source"
    if path.suffix.lower() in {".md", ".txt", ".html", ".htm"}:
        return "article"
    if path.suffix.lower() in {".json", ".jsonl", ".csv"}:
        return "manifest"
    return "unknown"


def _detect_title(path: Path) -> str:
    stem = path.stem.replace("_", " ").replace("-", " ").strip()
    return re.sub(r"\s+", " ", stem)


def _detect_author(path: Path) -> str:
    stem = _detect_title(path)
    if " by " in stem.lower():
        before, after = re.split(r"\s+by\s+", stem, maxsplit=1, flags=re.IGNORECASE)
        if before and after:
            return after.strip()
    return ""


def _detect_date(text: str) -> str:
    match = re.search(r"(20\d{2}|19\d{2})[-_ ]?([01]\d)?[-_ ]?([0-3]\d)?", text)
    if not match:
        return ""
    year, month, day = match.group(1), match.group(2), match.group(3)
    if month and day:
        return f"{year}-{month}-{day}"
    if month:
        return f"{year}-{month}"
    return year


def _cluster_suggestion(corpus: str, path: Path) -> str:
    text = f"{corpus} {path.as_posix()}".lower()
    if "mosaic" in text or "sermon" in text:
        return "mosaic_sermons"
    if "youtube" in text or "transcript" in text or "watch" in text:
        return "youtube_backlog"
    if "apolog" in text or "reasonable" in text:
        return "apologetics"
    if "theolog" in text or "christian" in text:
        return "theology"
    if "biblical" in text or "bible" in text:
        return "biblical_studies"
    if "philosophy" in text or "argument" in text:
        return "philosophy"
    return "unknown"


def _role_suggestion(source_type: str) -> str:
    if source_type in {"youtube_transcript", "sermon_transcript"}:
        return "transcript"
    if source_type == "book_source":
        return "primary_source"
    if source_type == "manifest":
        return "manifest"
    if source_type == "packet":
        return "packet"
    if source_type == "article":
        return "background"
    return "unknown"


def scan_result_asdict(result: ArchiveScanResult) -> dict[str, Any]:
    return asdict(result)
