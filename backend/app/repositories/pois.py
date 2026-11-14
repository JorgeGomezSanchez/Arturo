"""POI storage abstraction.

The API only talks to :class:`PoiRepository`. Implementations:

* :class:`JsonFilePoiRepository` — one JSON file on disk (default,
  ``POI_STORE=json``). Atomic writes (temp file + rename) and a lock, so
  concurrent requests never corrupt it. Ideal for a single habitat
  laptop: no database server, trivially backed up or synced.
* :class:`MemoryPoiRepository` — in RAM (``POI_STORE=memory``), for tests
  and throwaway demos.

Swapping in SQLite, a habitat database or a "Martian network" sync
service = writing another subclass and a branch in
:func:`build_poi_repository`. Endpoints and frontend stay untouched.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.config import Settings
from app.models.poi import Poi, PoiInput


class PoiNotFoundError(KeyError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class PoiRepository(ABC):
    name = "abstract"

    @abstractmethod
    def list(self) -> list[Poi]: ...

    @abstractmethod
    def get(self, poi_id: str) -> Poi:
        """Raises PoiNotFoundError."""

    @abstractmethod
    def create(self, data: PoiInput) -> Poi: ...

    @abstractmethod
    def update(self, poi_id: str, data: PoiInput) -> Poi:
        """Full replace of the editable fields. Raises PoiNotFoundError."""

    @abstractmethod
    def delete(self, poi_id: str) -> None:
        """Raises PoiNotFoundError."""

    def describe(self) -> str:
        return self.name


class MemoryPoiRepository(PoiRepository):
    name = "memory"

    def __init__(self, pois: Optional[list[Poi]] = None):
        self._pois: dict[str, Poi] = {p.id: p for p in pois or []}
        self._lock = threading.RLock()

    def list(self) -> list[Poi]:
        with self._lock:
            return sorted(self._pois.values(), key=lambda p: p.created_at)

    def get(self, poi_id: str) -> Poi:
        with self._lock:
            try:
                return self._pois[poi_id]
            except KeyError:
                raise PoiNotFoundError(poi_id) from None

    def create(self, data: PoiInput) -> Poi:
        now = _now()
        poi = Poi(id=uuid.uuid4().hex, created_at=now, updated_at=now, **data.model_dump())
        with self._lock:
            self._pois[poi.id] = poi
            self._changed()
        return poi

    def update(self, poi_id: str, data: PoiInput) -> Poi:
        with self._lock:
            old = self.get(poi_id)
            poi = Poi(id=old.id, created_at=old.created_at, updated_at=_now(), **data.model_dump())
            self._pois[poi_id] = poi
            self._changed()
            return poi

    def delete(self, poi_id: str) -> None:
        with self._lock:
            self.get(poi_id)
            del self._pois[poi_id]
            self._changed()

    def _changed(self) -> None:
        """Hook for persistent subclasses (called with the lock held)."""


class JsonFilePoiRepository(MemoryPoiRepository):
    """Memory repository mirrored to a JSON file after every change."""

    name = "json"

    def __init__(self, path: Path):
        self.path = Path(path)
        super().__init__(self._load())

    def _load(self) -> list[Poi]:
        if not self.path.is_file():
            return []
        with open(self.path, encoding="utf-8") as fh:
            raw = json.load(fh)
        return [Poi.model_validate(item) for item in raw.get("pois", [])]

    def _changed(self) -> None:
        payload = {
            "version": 1,
            "pois": [p.model_dump(mode="json", by_alias=True) for p in self.list()],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".part")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def describe(self) -> str:
        return f"json ({self.path})"


def build_poi_repository(settings: Settings) -> PoiRepository:
    if settings.poi_store == "memory":
        return MemoryPoiRepository()
    return JsonFilePoiRepository(settings.poi_store_file)
