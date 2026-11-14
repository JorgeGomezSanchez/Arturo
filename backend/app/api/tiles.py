"""Tile endpoint: the frontend's only access to imagery."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Request, Response

from app.catalog.registry import LayerNotFoundError
from app.providers.base import TileNotFoundError, TileProviderError
from app.services.tiles import TileService

router = APIRouter(tags=["tiles"])


@router.get(
    "/tiles/{layer_id}/{z}/{x}/{y}",
    summary="Map tile",
    responses={
        200: {"content": {"image/png": {}, "image/jpeg": {}}, "description": "Image"},
        404: {"description": "Unknown layer or tile without data"},
        502: {"description": "The data source failed"},
    },
    response_class=Response,
)
async def get_tile(
    request: Request,
    layer_id: str,
    z: int = Path(..., ge=0, le=24, description="Native source level"),
    x: int = Path(..., ge=0, description="Column (from -180° eastwards)"),
    y: int = Path(..., ge=0, description="Row (from +90° southwards)"),
) -> Response:
    service: TileService = request.app.state.tile_service
    try:
        tile = await service.get_tile(layer_id, z, x, y)
    except LayerNotFoundError:
        raise HTTPException(status_code=404, detail=f"Layer '{layer_id}' does not exist")
    except TileNotFoundError:
        raise HTTPException(status_code=404, detail="Tile without data")
    except TileProviderError as exc:
        raise HTTPException(status_code=502, detail=f"Data source error: {exc}")

    return Response(
        content=tile.content,
        media_type=tile.media_type,
        headers={
            # Tiles never change: let the browser cache them for a week.
            "Cache-Control": "public, max-age=604800, immutable",
            "X-Tile-Origin": tile.origin,
        },
    )
