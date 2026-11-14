import { useEffect, useState } from 'react'
import FeatureLabels from './components/FeatureLabels'
import Header from './components/Header'
import LayersPanel from './components/LayersPanel'
import LegendPanel from './components/LegendPanel'
import MarsMap from './components/MarsMap'
import PoiLayer from './components/PoiLayer'
import PoiPanel from './components/PoiPanel'
import PoiSheet from './components/PoiSheet'
import Sidebar from './components/Sidebar'
import ZonesPanel from './components/ZonesPanel'
import { useBackendData } from './hooks/useBackendData'
import { useLabelState } from './hooks/useLabelState'
import { useLayerState } from './hooks/useLayerState'
import { usePois } from './hooks/usePois'
import './App.css'

/**
 * POI interaction state machine:
 *   null                         idle
 *   { mode: 'placing' }          waiting for a tap on the map
 *   { mode: 'create', draft }    form for a new POI at draft {lat, lon, zoom}
 *   { mode: 'view', id }         details of an existing POI
 *   { mode: 'edit', id }         form for an existing POI
 */
function MapApp({ data }) {
  // Leaflet map instance, shared with panels that live outside the map.
  const [map, setMap] = useState(null)
  const [tab, setTab] = useState('layers')
  const layerState = useLayerState(data.layers)
  const labels = useLabelState(data.featureCategories)
  const pois = usePois()
  const [poiUi, setPoiUi] = useState(null)
  const [draftLook, setDraftLook] = useState({})

  const rules = data.mapConfig.poiVisibility
  const colors = Object.fromEntries(data.poiCategories.map((c) => [c.id, c.color]))
  const placing = poiUi?.mode === 'placing'
  const current = poiUi?.id ? pois.pois.find((p) => p.id === poiUi.id) : null

  // Crosshair cursor while placing; Esc cancels.
  useEffect(() => {
    if (!map) return
    map.getContainer().classList.toggle('placing', placing)
    if (!placing) return
    const onKey = (e) => e.key === 'Escape' && setPoiUi(null)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [map, placing])

  const startPlacing = () => {
    setDraftLook({})
    setPoiUi({ mode: 'placing' })
  }
  const openPoi = (poi) => {
    const [lon, lat] = poi.geometry.coordinates
    map?.flyTo([lat, lon], Math.max(poi.properties.createdZoom, data.mapConfig.minZoom), { duration: 1.2 })
    setPoiUi({ mode: 'view', id: poi.id })
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
          interactive={!poiUi}
        />
        <PoiLayer
          pois={pois.pois}
          rules={rules}
          colors={colors}
          selectedId={poiUi?.id}
          onSelect={(poi) => setPoiUi({ mode: 'view', id: poi.id })}
          placing={placing}
          onPlace={(draft) => setPoiUi({ mode: 'create', draft })}
          draft={poiUi?.mode === 'create' ? { ...poiUi.draft, category: 'unknown', ...draftLook } : null}
        />
      </MarsMap>

      <Sidebar header={<Header health={data.health} />} tabs={tabs} activeTab={tab} onTabChange={setTab} />
      <LegendPanel layers={data.layers} layerState={layerState} />

      {/* Floating action button: always reachable with a thumb */}
      {!poiUi && (
        <button className="fab" onClick={startPlacing} aria-label="Add a point of interest">
          ＋ POI
        </button>
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
