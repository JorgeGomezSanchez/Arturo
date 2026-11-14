"""Layer catalog endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.catalog.registry import LayerNotFoundError, get_registry
from app.models.layer import LayerOut

router = APIRouter(tags=["layers"])


@router.get(
    "/layers",
    response_model=list[LayerOut],
    response_model_by_alias=True,
    summary="List available layers",
)
def list_layers() -> list[LayerOut]:
    """Return every layer with what is needed to render it.

    The ``tileUrl`` field always points to this backend
    (``/api/tiles/{id}/{z}/{x}/{y}``), never to NASA.
    """
    return [LayerOut.from_config(layer) for layer in get_registry().all()]


@router.get(
    "/layers/{layer_id}",
    response_model=LayerOut,
    response_model_by_alias=True,
    summary="Layer details",
)
def get_layer(layer_id: str) -> LayerOut:
    try:
        return LayerOut.from_config(get_registry().get(layer_id))
    except LayerNotFoundError:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' does not exist")
