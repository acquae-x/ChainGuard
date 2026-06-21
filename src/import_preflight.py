from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path


DISK_MULTIPLIER: float = 2.5
SQLITE_SOFT_LIMIT_BYTES: int = 5 * 1024**3
_SAMPLE_LINES: int = 200


@dataclass(frozen=True)
class ResourceProbe:
    free_disk_bytes: int
    available_ram_bytes: int | None
    ram_source: str


@dataclass(frozen=True)
class PreflightReport:
    incoming_bytes: int
    estimated_rows: int
    largest_file_bytes: int
    required_disk_bytes: int
    free_disk_bytes: int
    disk_shortfall_bytes: int
    disk_ok: bool
    recommend_postgres: bool
    available_ram_bytes: int | None
    verdict: str
    can_proceed: bool
    messages: list[str] = field(default_factory=list)


def probe_resources(target_path: str | Path) -> ResourceProbe:
    """Probe disk with stdlib; RAM uses optional psutil and degrades cleanly."""
    free_disk = shutil.disk_usage(_existing_dir(target_path)).free
    try:
        import psutil

        return ResourceProbe(free_disk, int(psutil.virtual_memory().available), "psutil")
    except Exception:
        return ResourceProbe(free_disk, None, "unavailable")


def estimate_incoming(csv_paths: list[str | Path]) -> tuple[int, int, int]:
    """Return total bytes, estimated rows, and largest file bytes without full reads."""
    total = 0
    largest = 0
    estimated_rows = 0
    for raw_path in csv_paths:
        path = Path(raw_path)
        size = path.stat().st_size
        total += size
        largest = max(largest, size)
        avg = _avg_line_bytes(path)
        estimated_rows += int(size / avg) if avg > 0 else 0
    return total, estimated_rows, largest


def run_preflight(
    csv_paths: list[str | Path],
    target_db_path: str | Path,
) -> PreflightReport:
    incoming, rows, largest = estimate_incoming(csv_paths)
    probe = probe_resources(Path(target_db_path).parent)
    required = int(incoming * DISK_MULTIPLIER)
    shortfall = max(0, required - probe.free_disk_bytes)
    disk_ok = shortfall == 0
    recommend_postgres = incoming > SQLITE_SOFT_LIMIT_BYTES

    messages = [
        (
            f"Incoming data: {_gb(incoming)} "
            f"(estimated {rows:,} rows, largest file {_gb(largest)})"
        ),
        (
            f"Estimated disk needed: {_gb(required)} "
            f"(data x {DISK_MULTIPLIER}); free disk: {_gb(probe.free_disk_bytes)}"
        ),
    ]
    if not disk_ok:
        verdict = "INSUFFICIENT_DISK"
        can_proceed = False
        messages.append(
            "Insufficient disk: need "
            f"{_gb(shortfall)} more. Clear space or choose a larger disk."
        )
    elif recommend_postgres:
        verdict = "REVIEW"
        can_proceed = True
        messages.append(
            "Data is above 5 GB. Import can proceed, but PostgreSQL via "
            "DATABASE_URL is recommended for production query performance."
        )
    else:
        verdict = "OK"
        can_proceed = True
        messages.append("Capacity check passed; import can proceed.")

    if probe.ram_source == "unavailable":
        messages.append(
            "RAM was not detected because psutil is unavailable; streaming import "
            "keeps memory usage bounded, so disk is the gating check."
        )

    return PreflightReport(
        incoming_bytes=incoming,
        estimated_rows=rows,
        largest_file_bytes=largest,
        required_disk_bytes=required,
        free_disk_bytes=probe.free_disk_bytes,
        disk_shortfall_bytes=shortfall,
        disk_ok=disk_ok,
        recommend_postgres=recommend_postgres,
        available_ram_bytes=probe.available_ram_bytes,
        verdict=verdict,
        can_proceed=can_proceed,
        messages=messages,
    )


def _avg_line_bytes(path: str | Path) -> float:
    total = 0
    count = 0
    with Path(path).open("rb") as handle:
        for line in handle:
            total += len(line)
            count += 1
            if count >= _SAMPLE_LINES:
                break
    return total / count if count else 0.0


def _existing_dir(target_path: str | Path) -> Path:
    path = Path(target_path)
    if path.exists():
        return path if path.is_dir() else path.parent

    current = path if path.suffix == "" else path.parent
    while current != current.parent:
        if current.exists():
            return current if current.is_dir() else current.parent
        current = current.parent
    return current


def _gb(num_bytes: int) -> str:
    if num_bytes >= 1024**3:
        return f"{num_bytes / 1024**3:.2f} GB"
    if num_bytes >= 1024**2:
        return f"{num_bytes / 1024**2:.2f} MB"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.2f} KB"
    return f"{num_bytes} B"
