"""POI storage implementations (no HTTP)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.models.poi import PoiInput
from app.repositories.pois import JsonFilePoiRepository, MemoryPoiRepository, PoiNotFoundError


def sample(**kw) -> PoiInput:
    data = {"name": "Ice cliff", "category": "resource", "notes": "", "lat": 40.0, "lon": -170.0, "createdZoom": 6}
    data.update(kw)
    return PoiInput.model_validate(data)


@pytest.mark.parametrize("make", [lambda p: MemoryPoiRepository(), lambda p: JsonFilePoiRepository(p / "pois.json")])
def test_crud_roundtrip(tmp_path, make):
    repo = make(tmp_path)
    poi = repo.create(sample())
    assert repo.get(poi.id).name == "Ice cliff"
    updated = repo.update(poi.id, sample(name="Ice cliff (north)", category="hazard"))
    assert updated.created_at == poi.created_at and updated.category == "hazard"
    assert [p.id for p in repo.list()] == [poi.id]
    repo.delete(poi.id)
    assert repo.list() == []
    with pytest.raises(PoiNotFoundError):
        repo.get(poi.id)
    with pytest.raises(PoiNotFoundError):
        repo.delete(poi.id)


def test_json_file_persists_across_instances(tmp_path):
    path = tmp_path / "sub" / "pois.json"
    poi = JsonFilePoiRepository(path).create(sample())
    again = JsonFilePoiRepository(path)
    assert again.get(poi.id).lat == 40.0
    raw = json.loads(path.read_text())
    assert raw["version"] == 1 and raw["pois"][0]["createdZoom"] == 6
    assert not list(path.parent.glob("*.part"))  # atomic write left no temp files


def test_input_validation_and_normalisation():
    assert sample(lon=200).lon == -160  # unwrapped Leaflet longitude
    assert sample(name="  Base  ").name == "Base"
    for bad in ({"name": "   "}, {"category": "pizza"}, {"lat": 91}, {"createdZoom": -1}, {"name": "x" * 61}):
        with pytest.raises(ValidationError):
            sample(**bad)
