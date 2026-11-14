"""Hand-drawn routes: CRUD as GeoJSON + hazard analysis.

Routes are stored through a swappable RouteRepository (like POIs). Every
create/update re-runs the analysis and stores its summary in
``properties.stats``; the full analysis (profile, hazards, coloured
segments) comes from ``POST /api/routes/analyze`` or
``GET /api/routes/{id}/analysis``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from app.models.route import (
    AnalyzeRequest, RouteAnalysis, RouteFeature, RouteFeatureCollection, RouteInput, RoutesConfig, RouteStats,
)
from app.repositories.routes import RouteNotFoundError, RouteRepository
from app.services.route_analysis import RouteAnalysisError, RouteAnalyzer

router = APIRouter(tags=["routes"])


def _repo(request: Request) -> RouteRepository:
    return request.app.state.route_repository


def _analyzer(request: Request) -> RouteAnalyzer:
    return request.app.state.route_analyzer


def _not_found(route_id: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"Route '{route_id}' does not exist")


def _analyze(request: Request, req: AnalyzeRequest) -> RouteAnalysis:
    try:
        return _analyzer(request).analyze(req)
    except RouteAnalysisError as exc:
        raise HTTPException(422, str(exc))


def _stats(request: Request, body: RouteInput) -> RouteStats:
    a = _analyze(request, AnalyzeRequest(coordinates=body.coordinates(), mode=body.mode))
    return RouteStats(
        distance_m=a.distance_m, duration_h=a.duration_h, dose_msv=a.dose_msv, gain_m=a.gain_m, loss_m=a.loss_m,
        max_slope_deg=a.max_slope_deg, max_severity=a.max_severity, hazard_counts=a.hazard_counts, mode=a.mode,
        resolution=a.resolution, analyzed_at=datetime.now(timezone.utc).replace(microsecond=0),
    )


@router.get("/routes/config", response_model=RoutesConfig, response_model_by_alias=True,
            summary="Travel modes and hazard thresholds (routes.yaml)")
def routes_config(request: Request) -> RoutesConfig:
    return _analyzer(request).config


@router.post("/routes/analyze", response_model=RouteAnalysis, response_model_by_alias=True,
             summary="Analyse a line: profile, statistics, hazards, coloured segments")
def analyze_route(request: Request, body: AnalyzeRequest) -> RouteAnalysis:
    """Samples the line along great circles at the resolution of the best
    elevation data available and checks every hazard rule of routes.yaml."""
    return _analyze(request, body)


@router.get("/routes", response_model=RouteFeatureCollection, response_model_by_alias=True,
            summary="List saved routes (GeoJSON LineStrings)")
def list_routes(request: Request) -> RouteFeatureCollection:
    return RouteFeatureCollection(features=[RouteFeature.from_route(r) for r in _repo(request).list()])


@router.get("/routes/{route_id}", response_model=RouteFeature, response_model_by_alias=True,
            summary="One route")
def get_route(request: Request, route_id: str) -> RouteFeature:
    try:
        return RouteFeature.from_route(_repo(request).get(route_id))
    except RouteNotFoundError:
        raise _not_found(route_id)


@router.get("/routes/{route_id}/analysis", response_model=RouteAnalysis, response_model_by_alias=True,
            summary="Fresh analysis of a saved route")
def get_route_analysis(request: Request, route_id: str,
                       ls: Optional[float] = Query(None, ge=0, lt=360)) -> RouteAnalysis:
    try:
        r = _repo(request).get(route_id)
    except RouteNotFoundError:
        raise _not_found(route_id)
    return _analyze(request, AnalyzeRequest(coordinates=r.coordinates(), mode=r.mode, ls=ls))


@router.post("/routes", response_model=RouteFeature, response_model_by_alias=True,
             status_code=status.HTTP_201_CREATED, summary="Create a route (analysed on save)")
def create_route(request: Request, body: RouteInput) -> RouteFeature:
    return RouteFeature.from_route(_repo(request).create(body, _stats(request, body)))


@router.put("/routes/{route_id}", response_model=RouteFeature, response_model_by_alias=True,
            summary="Replace a route (name, notes, mode, ends, waypoints); re-analysed")
def update_route(request: Request, route_id: str, body: RouteInput) -> RouteFeature:
    repo = _repo(request)
    try:
        repo.get(route_id)
    except RouteNotFoundError:
        raise _not_found(route_id)
    return RouteFeature.from_route(repo.update(route_id, body, _stats(request, body)))


@router.delete("/routes/{route_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a route")
def delete_route(request: Request, route_id: str) -> Response:
    try:
        _repo(request).delete(route_id)
    except RouteNotFoundError:
        raise _not_found(route_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
