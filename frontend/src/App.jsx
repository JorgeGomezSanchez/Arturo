import { useCallback, useEffect, useMemo, useState } from 'react'
import L from 'leaflet'
import FeatureLabels from './components/FeatureLabels'
import Header from './components/Header'
import LayersPanel from './components/LayersPanel'
import LegendPanel from './components/LegendPanel'
import MarsMap from './components/MarsMap'
import CreditsControl from './components/CreditsControl'
import PoiLayer from './components/PoiLayer'
import PoiPanel from './components/PoiPanel'
import PoiSheet from './components/PoiSheet'
import PointPanel from './components/PointPanel'
import PointQuery from './components/PointQuery'
import RouteLayer from './components/RouteLayer'
import RoutePanel from './components/RoutePanel'
import RoutesPanel from './components/RoutesPanel'
import Sidebar from './components/Sidebar'
import ZonesPanel from './components/ZonesPanel'
import { useBackendData } from './hooks/useBackendData'
import { useLabelState } from './hooks/useLabelState'
import { useLayerState } from './hooks/useLayerState'
import { usePois } from './hooks/usePois'
import { useRouteAnalysis } from './hooks/useRouteAnalysis'
import { useRoutePlan } from './hooks/useRoutePlan'
import { useRoutes } from './hooks/useRoutes'
import { defaultRouteName, routeCoordinates, snapRouteEnd, unwrapLine } from './map/routes'
import './App.css'

/**
 * POI interaction state machine:
 *   null                         idle
 *   { mode: 'placing' }          waiting for a tap on the map
 *   { mode: 'create', draft }    form for a new POI at draft {lat, lon, zoom}
 *   { mode: 'view', id }         details of an existing POI
 *   { mode: 'edit', id }         form for an existing POI
 *
 * Route state machine (routeUi), exclusive with the POI one:
 *   null                              idle
 *   { mode: 'pickA' }                 waiting for the start tap
 *   { mode: 'pickB', start }          waiting for the end tap
 *   { mode: 'edit', id, draft, dirty } route open (id null = not saved yet)
 * draft = { name, notes, mode, start, end, waypoints } (RouteInput shape).
 */

/** Map padding that keeps a fitted area clear of the route panel. */
function panelPadding(map) {
  const phone = window.matchMedia?.('(max-width: 700px)').matches
  const h = map.getSize().y
  return phone
    ? { paddingTopLeft: [24, 190], paddingBottomRight: [24, Math.round(h * 0.52)] }
    : { paddingTopLeft: [40, 40], paddingBottomRight: [420, 40] }
}

function fitLine(map, coords, maxZoom) {
  const line = unwrapLine(coords, map.getCenter().lng)
  const b = L.latLngBounds(line)
  map.flyToBounds(b, { ...panelPadding(map), maxZoom, duration: 0.9 })
}

function draftOf(feature) {
  const p = feature.properties
  return {
    name: p.name,
    notes: p.notes,
    mode: p.mode,
    start: p.start,
    end: p.end,
    waypoints: feature.geometry.coordinates.slice(1, -1),
  }
}
function MapApp({ data }) {
  // Leaflet map instance, shared with panels that live outside the map.
  const [map, setMap] = useState(null)
  const [tab, setTab] = useState('layers')
  const layerState = useLayerState(data.layers)
  const labels = useLabelState(data.featureCategories)
  const pois = usePois()
  const [poiUi, setPoiUi] = useState(null)
  const [draftLook, setDraftLook] = useState({})
  // Location panel: { lat, lon, title?, poiId? } or null.
  const [pointTarget, setPointTarget] = useState(null)
  const closePoint = useCallback(() => setPointTarget(null), [])
  const routes = useRoutes()
  const [routeUi, setRouteUi] = useState(null)
  const [hazardId, setHazardId] = useState(null)
  const [cursorD, setCursorD] = useState(null)
  const routeDraft = routeUi?.mode === 'edit' ? routeUi.draft : null
  const routeCoords = useMemo(() => (routeDraft ? routeCoordinates(routeDraft) : null), [routeDraft])
  const analysis = useRouteAnalysis(routeCoords, routeDraft?.mode)
  const planner = useRoutePlan()
  const routePicking = routeUi?.mode === 'pickA' ? 'A' : routeUi?.mode === 'pickB' ? 'B' : null

  const rules = data.mapConfig.poiVisibility
  const colors = Object.fromEntries(data.poiCategories.map((c) => [c.id, c.color]))
  const placing = poiUi?.mode === 'placing'
  const current = poiUi?.id ? pois.pois.find((p) => p.id === poiUi.id) : null

  // Crosshair cursor while placing a POI or picking route ends; Esc cancels.
  useEffect(() => {
    if (!map) return
    const on = placing || !!routePicking
    map.getContainer().classList.toggle('placing', on)
    if (!on) return
    const onKey = (e) => {
      if (e.key !== 'Escape') return
      setPoiUi(null)
      setRouteUi(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [map, placing, routePicking])

  // ---- routes ----
  const snapOpts = { pois: pois.pois, categories: labels.categories, labelsOn: labels.anyOn }
  const startRoute = () => {
    planner.clear()
    setPointTarget(null)
    setPoiUi(null)
    setHazardId(null)
    setCursorD(null)
    setTab('routes')
    setRouteUi({ mode: 'pickA' })
  }
  const onPick = async (latlng) => {
    const end = await snapRouteEnd(map, latlng, snapOpts)
    setRouteUi((ui) => {
      if (ui?.mode === 'pickA') return { mode: 'pickB', start: end }
      if (ui?.mode === 'pickB') {
        const draft = { name: defaultRouteName(ui.start, end), notes: '', mode: 'walking', start: ui.start, end, waypoints: [] }
        return { mode: 'edit', id: null, draft, dirty: true }
      }
      return ui
    })
  }
  const editDraft = (fn) => {
    setHazardId(null)
    setCursorD(null)
    planner.clear() // a manual edit makes the plan summary stale
    setRouteUi((ui) => (ui?.mode === 'edit' ? { ...ui, draft: fn(ui.draft), dirty: true } : ui))
  }
  const moveVertex = async (index, latlng) => {
    const n = routeDraft.waypoints.length + 2
    if (index === 0 || index === n - 1) {
        const end = await snapRouteEnd(map, latlng, snapOpts)
      editDraft((d) => (index === 0 ? { ...d, start: end } : { ...d, end }))
      return
    }
    const w = latlng.wrap()
    editDraft((d) => ({ ...d, waypoints: d.waypoints.map((p, i) => (i === index - 1 ? [w.lng, w.lat] : p)) }))
  }
  const insertVertex = (index, latlng) => {
    const w = latlng.wrap()
    editDraft((d) => {
      const wps = [...d.waypoints]
      wps.splice(index - 1, 0, [w.lng, w.lat])
      return { ...d, waypoints: wps }
    })
  }
  const removeWaypoint = (i) => editDraft((d) => ({ ...d, waypoints: d.waypoints.filter((_, k) => k !== i) }))
  // "Auto": replace the waypoints with a planned, hazard-avoiding path.
  // They stay ordinary waypoints, so the route can still be dragged.
  const autoPlan = (weights) => {
    setHazardId(null)
    setCursorD(null)
    planner.run(routeDraft, {
      weights,
      onWaypoints: (waypoints) => {
        setRouteUi((ui) => (ui?.mode === 'edit' ? { ...ui, draft: { ...ui.draft, waypoints }, dirty: true } : ui))
        if (map) fitLine(map, routeCoordinates({ ...routeDraft, waypoints }), 13)
      },
    })
  }
  const undoPlan = () => {
    const prev = planner.plan?.prevWaypoints
    planner.clear()
    if (prev) setRouteUi((ui) => (ui?.mode === 'edit' ? { ...ui, draft: { ...ui.draft, waypoints: prev }, dirty: true } : ui))
  }
  const openRoute = (feature) => {
    planner.clear()
    setPointTarget(null)
    setPoiUi(null)
    setHazardId(null)
    setCursorD(null)
    setRouteUi({ mode: 'edit', id: feature.id, draft: draftOf(feature), dirty: false })
    if (map) fitLine(map, feature.geometry.coordinates, 12)
  }
  const selectHazard = (h) => {
    setHazardId(h.id)
    setCursorD(null)
    if (!map) return
    if (h.scope === 'route' || !h.coordinates?.length) {
      if (routeCoords) fitLine(map, routeCoords, 12)
    } else if (h.coordinates.length > 1) {
      fitLine(map, h.coordinates, 12)
    } else {
      map.flyTo([h.lat, h.lon], Math.max(map.getZoom(), 10), { duration: 0.9 })
    }
  }
  const saveRoute = async () => {
    const body = { ...routeDraft, name: routeDraft.name.trim(), createdZoom: map?.getZoom() ?? 0 }
    const f = routeUi.id ? await routes.update(routeUi.id, body) : await routes.create(body)
    setRouteUi((ui) => (ui?.mode === 'edit' ? { ...ui, id: f.id, dirty: false } : ui))
  }
  const closeRoute = () => {
    if (routeUi?.dirty && !window.confirm('Discard the changes to this route?')) return
    planner.clear()
    setRouteUi(null)
    setHazardId(null)
    setCursorD(null)
  }
  // While a route is open, labels and POI markers let taps and drags
  // through to the map (snapping, grabbing the line).
  useEffect(() => {
    map?.getContainer().classList.toggle('route-mode', !!routeUi)
  }, [map, routeUi])
  // Fit a freshly drawn route once.
  const newRouteKey = routeUi?.mode === 'edit' && !routeUi.id ? `${routeDraft.start.lat},${routeDraft.end.lat}` : null
  useEffect(() => {
    if (map && newRouteKey && routeCoords) fitLine(map, routeCoords, Math.max(map.getZoom(), 6))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, newRouteKey])
  const cursorPoint =
    cursorD != null && analysis.data
      ? analysis.data.profile.reduce((b, p) => (Math.abs(p.d - cursorD) < Math.abs(b.d - cursorD) ? p : b))
      : null

  const startPlacing = () => {
    setPointTarget(null)
    setDraftLook({})
    setPoiUi({ mode: 'placing' })
  }
  const openPoi = (poi) => {
    const [lon, lat] = poi.geometry.coordinates
    map?.flyTo([lat, lon], Math.max(poi.properties.createdZoom, data.mapConfig.minZoom), { duration: 1.2 })
    setPointTarget(null)
    setPoiUi({ mode: 'view', id: poi.id })
  }
  // Tap on the map (idle or while a POI card is just being viewed).
  const queryPoint = ({ lat, lon }) => {
    if (poiUi?.mode === 'view') setPoiUi(null)
    setPointTarget({ lat, lon })
  }
  const poiInfo = (poi) => {
    const [lon, lat] = poi.geometry.coordinates
    setPoiUi(null)
    setPointTarget({ lat, lon, title: poi.properties.name, poiId: poi.id })
  }
  // Panel opened from a POI card: offer a way back to the card.
  const pointPanelTarget = pointTarget && {
    ...pointTarget,
    onBack: pointTarget.poiId
      ? () => {
          setPoiUi({ mode: 'view', id: pointTarget.poiId })
          setPointTarget(null)
        }
      : undefined,
  }

  const tabs = [
    {
      id: 'layers',
      label: 'Layers',
      content: (
        <LayersPanel
          layers={data.layers}
          layerState={layerState}
          labelGroups={labels.groups}
          labelState={labels.state}
          onToggleLabels={labels.toggle}
        />
      ),
    },
    {
      id: 'pois',
      label: 'POIs',
      badge: pois.pois.length || null,
      content: (
        <PoiPanel
          pois={pois.pois}
          categories={data.poiCategories}
          rules={rules}
          error={pois.error}
          placing={placing}
          onStartPlacing={startPlacing}
          onCancelPlacing={() => setPoiUi(null)}
          onOpen={openPoi}
        />
      ),
    },
    {
      id: 'routes',
      label: 'Routes',
      badge: routes.routes.length || null,
      content: (
        <RoutesPanel
          routes={routes.routes}
          config={routes.config}
          error={routes.error}
          picking={!!routePicking}
          activeId={routeUi?.id}
          onNew={startRoute}
          onCancel={() => setRouteUi(null)}
          onOpen={openRoute}
        />
      ),
    },
    {
      id: 'zones',
      label: 'Zones',
      content: <ZonesPanel map={map} zones={data.zones} mapConfig={data.mapConfig} />,
    },
  ]

  return (
    <div className="app">
      <MarsMap mapConfig={data.mapConfig} layers={data.layers} layerState={layerState} onMapReady={setMap}>
        <FeatureLabels
          enabled={labels.anyOn}
          categories={labels.categories}
          pois={pois.pois}
          poiRules={rules}
          interactive={!poiUi && !routeUi}
        />
        <PoiLayer
          pois={pois.pois}
          rules={rules}
          colors={colors}
          selectedId={poiUi?.id}
          onSelect={(poi) => {
            setPointTarget(null)
            setPoiUi({ mode: 'view', id: poi.id })
          }}
          placing={placing}
          locked={!!routeUi}
          onPlace={(draft) => setPoiUi({ mode: 'create', draft })}
          draft={poiUi?.mode === 'create' ? { ...poiUi.draft, category: 'unknown', ...draftLook } : null}
        />
        <PointQuery
          enabled={(!poiUi || poiUi.mode === 'view') && !routeUi}
          point={pointTarget}
          onQuery={queryPoint}
        />
        <RouteLayer
          routes={routes.routes}
          activeId={routeUi?.id}
          draft={routeDraft}
          picking={routePicking}
          pickStart={routeUi?.start}
          analysis={analysis}
          selectedHazardId={hazardId}
          cursor={cursorPoint}
          onPick={onPick}
          onSelectRoute={openRoute}
          onMoveVertex={moveVertex}
          onInsertVertex={insertVertex}
          onRemoveWaypoint={removeWaypoint}
          onSelectHazard={selectHazard}
        />
      </MarsMap>

      <Sidebar
        header={<Header health={data.health} />}
        tabs={tabs}
        activeTab={tab}
        onTabChange={setTab}
        autoCollapse={!!routeUi}
      />
      <LegendPanel layers={data.layers} layerState={layerState} />
      <CreditsControl
        map={map}
        layers={data.layers}
        layerState={layerState}
        labelGroups={labels.groups}
        labelState={labels.state}
        labelCredits={data.mapConfig.labelCredits}
      />

      {/* Floating action button: always reachable with a thumb */}
      {!poiUi && !pointTarget && !routeUi && (
        <>
          <button className="fab fab-route" onClick={startRoute} aria-label="Draw a new route">
            ↝ Route
          </button>
          <button className="fab" onClick={startPlacing} aria-label="Add a point of interest">
            ＋ POI
          </button>
        </>
      )}
      {routePicking && (
        <div className="hud placing-banner" role="status">
          <span>
            {routePicking === 'A' ? 'Tap the start (A): a POI, a label or any point' : 'Now tap the end (B)'}
          </span>
          <button className="btn" onClick={() => setRouteUi(null)}>
            Cancel
          </button>
        </div>
      )}
      {routeDraft && (
        <RoutePanel
          key={routeUi.id ?? 'new'}
          draft={routeDraft}
          saved={!!routeUi.id}
          dirty={routeUi.dirty}
          config={routes.config}
          analysis={analysis}
          selectedHazardId={hazardId}
          cursorD={cursorD}
          onChange={(patch) => {
            if (patch.mode) planner.clear()
            setRouteUi((ui) => ({ ...ui, draft: { ...ui.draft, ...patch }, dirty: true }))
          }}
          plan={planner.plan}
          planDefaults={routes.config?.planning}
          onAutoPlan={autoPlan}
          onUndoPlan={undoPlan}
          onSelectHazard={selectHazard}
          onCursor={setCursorD}
          onSave={saveRoute}
          onDelete={async () => {
            await routes.remove(routeUi.id)
            setRouteUi(null)
          }}
          onClose={closeRoute}
        />
      )}
      {placing && (
        <div className="hud placing-banner" role="status">
          <span>Tap the map where the POI goes</span>
          <button className="btn" onClick={() => setPoiUi(null)}>
            Cancel
          </button>
        </div>
      )}

      {poiUi?.mode === 'create' && (
        <PoiSheet
          key="create"
          mode="create"
          draft={poiUi.draft}
          categories={data.poiCategories}
          rules={rules}
          onDraftChange={(f) => setDraftLook({ name: f.name, category: f.category })}
          onSave={async (body) => {
            const created = await pois.create(body)
            setPoiUi({ mode: 'view', id: created.id })
          }}
          onCancel={() => setPoiUi(null)}
        />
      )}
      {current && (poiUi.mode === 'view' || poiUi.mode === 'edit') && (
        <PoiSheet
          key={`${poiUi.mode}-${current.id}`}
          mode={poiUi.mode}
          poi={current}
          categories={data.poiCategories}
          rules={rules}
          onEdit={() => setPoiUi({ mode: 'edit', id: current.id })}
          onInfo={() => poiInfo(current)}
          onSave={async (body) => {
            await pois.update(current.id, body)
            setPoiUi({ mode: 'view', id: current.id })
          }}
          onDelete={async () => {
            await pois.remove(current.id)
            setPoiUi(null)
          }}
          onCancel={() => setPoiUi(poiUi.mode === 'edit' ? { mode: 'view', id: current.id } : null)}
        />
      )}
      {pointPanelTarget && (
        <PointPanel target={pointPanelTarget} onClose={closePoint} />
      )}
    </div>
  )
}

export default function App() {
  const data = useBackendData()

  if (data.status === 'loading') {
    return <div className="screen-message">Loading Mars…</div>
  }
  if (data.status === 'error') {
    return (
      <div className="screen-message error">
        <p>Could not reach the Arturo backend.</p>
        <code>{String(data.error.message)}</code>
        <p>Is it running? (see README: uvicorn app.main:app --port 8000)</p>
      </div>
    )
  }
  return <MapApp data={data} />
}
