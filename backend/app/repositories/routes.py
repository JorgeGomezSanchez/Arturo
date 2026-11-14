"""Route storage abstraction (same design as POIs).

The API only talks to :class:`RouteRepository`. Implementations:

* :class:`JsonFileRouteRepository` — one JSON file (``ROUTE_STORE=json``,
  default), atomic writes and a lock.
* :class:`MemoryRouteRepository` — RAM only (``ROUTE_STORE=memory``).

A database or a habitat sync service is one more subclass plus a branch
in :func:`build_route_repository`; endpoints and frontend do not change.
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
from app.models.route import Route, RouteInput, RouteStats


class RouteNotFoundError(KeyError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class RouteRepository(ABC):
    name = "abstract"

    @abstractmethod
    def list(self) -> list[Route]: ...

    @abstractmethod
    def get(self, route_id: str) -> Route:
        """Raises RouteNotFoundError."""

    @abstractmethod
    def create(self, data: RouteInput, stats: Optional[RouteStats] = None) -> Route: ...

    @abstractmethod
    def update(self, route_id: str, data: RouteInput, stats: Optional[RouteStats] = None) -> Route:
        """Full replace of the editable fields. Raises RouteNotFoundError."""

    @abstractmethod
    def delete(self, route_id: str) -> None:
        """Raises RouteNotFoundError."""

    def describe(self) -> str:
        return self.name


class MemoryRouteRepository(RouteRepository):
    name = "memory"

    def __init__(self, routes: Optional[list[Route]] = None):
        self._routes: dict[str, Route] = {r.id: r for r in routes or []}
        self._lock = threading.RLock()

    def list(self) -> list[Route]:
        with self._lock:
            return sorted(self._routes.values(), key=lambda r: r.created_at)

    def get(self, route_id: str) -> Route:
        with self._lock:
            try:
                return self._routes[route_id]
            except KeyError:
                raise RouteNotFoundError(route_id) from None

    def create(self, data: RouteInput, stats: Optional[RouteStats] = None) -> Route:
        now = _now()
        route = Route(id=uuid.uuid4().hex, created_at=now, updated_at=now, stats=stats, **data.model_dump())
        with self._lock:
            self._routes[route.id] = route
            self._changed()
        return route

    def update(self, route_id: str, data: RouteInput, stats: Optional[RouteStats] = None) -> Route:
        with self._lock:
            old = self.get(route_id)
            route = Route(id=old.id, created_at=old.created_at, updated_at=_now(), stats=stats or old.stats,
                          **data.model_dump())
            self._routes[route_id] = route
            self._changed()
            return route

    def delete(self, route_id: str) -> None:
        with self._lock:
            self.get(route_id)
            del self._routes[route_id]
            self._changed()

    def _changed(self) -> None:
        """Hook for persistent subclasses (called with the lock held)."""


class JsonFileRouteRepository(MemoryRouteRepository):
    """Memory repository mirrored to a JSON file after every change."""

    name = "json"

    def __init__(self, path: Path):
        self.path = Path(path)
        super().__init__(self._load())

    def _load(self) -> list[Route]:
        if not self.path.is_file():
            return []
        with open(self.path, encoding="utf-8") as fh:
            raw = json.load(fh)
        return [Route.model_validate(item) for item in raw.get("routes", [])]

    def _changed(self) -> None:
        payload = {"version": 1, "routes": [r.model_dump(mode="json", by_alias=True) for r in self.list()]}
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


def build_route_repository(settings: Settings) -> RouteRepository:
    if settings.route_store == "memory":
        return MemoryRouteRepository()
    return JsonFileRouteRepository(settings.route_store_file)
