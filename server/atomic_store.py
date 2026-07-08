"""
Atomic, lock-protected, self-healing JSON storage utility.

Used by metadata.py and changelog.py to make JSON-file-as-database reads/writes
resilient against:
  - Partial/truncated writes (process killed mid-write, power loss, OOM)
  - Concurrent read-modify-write races (multiple requests touching the file
    at the same time under Flask's threaded=True dev server)
  - Silent data loss on corruption (previously: a corrupt file was treated
    as "empty", which could e.g. make the system think no admin exists)

Design:
  - AtomicJSONStore wraps a single JSON file path.
  - `load()` reads the file; on JSONDecodeError it logs a loud warning and
    falls back to the most recent backup snapshot instead of silently
    returning {}.
  - `save(data)` writes atomically: write to a temp file in the same
    directory, then os.replace() it over the real file (atomic on POSIX).
    Before writing, it snapshots the current on-disk content into a
    timestamped backup, pruning old backups beyond BACKUP_KEEP.
  - `transaction()` is a context manager that acquires a cross-process file
    lock (fcntl.flock) around a read-modify-write cycle, so
        with store.transaction() as data:
            data[key] = ...
    is safe even if the app is later run with multiple worker processes
    (a plain threading.Lock would NOT protect against that).

This module has no knowledge of metadata.json / changelog.json semantics —
it's a generic reusable primitive.
"""
import json
import fcntl
import logging
import shutil
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("webapps.atomic_store")

# How many timestamped backups to keep per store, oldest pruned first.
BACKUP_KEEP = 10


class AtomicJSONStore:
    """Atomic, lock-protected, self-healing JSON file store."""

    def __init__(self, path: Path, empty_default: Any = None):
        self.path = Path(path)
        self._empty_default = empty_default if empty_default is not None else {}
        self._backup_dir = self.path.parent / f".{self.path.stem}_backups"
        self._lock_path = self.path.parent / f".{self.path.name}.lock"

    # ── Loading ──────────────────────────────────────────────────────────

    def load(self) -> Any:
        """Load the JSON file. On corruption, log loudly and try to recover
        from the most recent backup instead of silently returning empty."""
        if not self.path.exists():
            return self._default()
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(
                f"AtomicJSONStore: {self.path.name} is corrupted or unreadable "
                f"({e}); attempting recovery from backup"
            )
            recovered = self._recover_from_backup()
            if recovered is not None:
                logger.warning(
                    f"AtomicJSONStore: recovered {self.path.name} from backup"
                )
                return recovered
            logger.warning(
                f"AtomicJSONStore: no usable backup for {self.path.name}; "
                f"falling back to empty default. DATA MAY HAVE BEEN LOST."
            )
            return self._default()

    def _default(self) -> Any:
        # Return a fresh copy so callers can't mutate a shared default
        return json.loads(json.dumps(self._empty_default))

    def _recover_from_backup(self):
        if not self._backup_dir.exists():
            return None
        backups = sorted(self._backup_dir.glob("*.json"), reverse=True)
        for bpath in backups:
            try:
                return json.loads(bpath.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
        return None

    # ── Saving ───────────────────────────────────────────────────────────

    def save(self, data: Any) -> None:
        """Atomically write `data` to the store's path, backing up the
        current on-disk content first."""
        self._backup_current()

        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        tmp_path.write_text(payload, encoding="utf-8")
        # os.replace is atomic on POSIX (and on Windows for files on the
        # same volume), so readers never observe a half-written file.
        tmp_path.replace(self.path)

    def _backup_current(self) -> None:
        """Snapshot the current file before overwriting it, and prune old
        backups beyond BACKUP_KEEP. Best-effort: never raises."""
        try:
            if not self.path.exists():
                return
            self._backup_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
            backup_path = self._backup_dir / f"{ts}.json"
            shutil.copyfile(self.path, backup_path)

            backups = sorted(self._backup_dir.glob("*.json"), reverse=True)
            for stale in backups[BACKUP_KEEP:]:
                stale.unlink(missing_ok=True)
        except OSError as e:
            logger.warning(f"AtomicJSONStore: backup failed for {self.path.name}: {e}")

    # ── Transactions (cross-process safe read-modify-write) ─────────────

    @contextmanager
    def transaction(self):
        """
        Context manager for an atomic read-modify-write cycle, safe across
        threads AND processes (uses an flock on a dedicated lock file, not a
        threading.Lock, so it remains correct even if the app is later run
        with multiple worker processes).

        Usage:
            with store.transaction() as data:
                data["some_key"] = "some_value"
            # data is automatically saved on clean exit; not saved if an
            # exception is raised inside the `with` block.
        """
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = open(self._lock_path, "w")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            data = self.load()
            yield data
            self.save(data)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()
