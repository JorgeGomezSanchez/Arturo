import { useState } from 'react'
import Header from './components/Header'
import LayersPanel from './components/LayersPanel'
import LegendPanel from './components/LegendPanel'
import MarsMap from './components/MarsMap'
import Sidebar from './components/Sidebar'
import ZonesPanel from './components/ZonesPanel'
import { useBackendData } from './hooks/useBackendData'
import { useLayerState } from './hooks/useLayerState'
import './App.css'

function MapApp({ data }) {
  // Leaflet map instance, shared with panels that live outside the map.
  const [map, setMap] = useState(null)
  const [tab, setTab] = useState('layers')
  const layerState = useLayerState(data.layers)

  const tabs = [
    {
      id: 'layers',
      label: 'Layers',
      content: <LayersPanel layers={data.layers} layerState={layerState} />,
    },
    {
      id: 'zones',
      label: 'Zones',
      content: <ZonesPanel map={map} zones={data.zones} mapConfig={data.mapConfig} />,
    },
  ]

  return (
    <div className="app">
      <MarsMap
        mapConfig={data.mapConfig}
        layers={data.layers}
        layerState={layerState}
        onMapReady={setMap}
      />
      <Sidebar
        header={<Header health={data.health} />}
        tabs={tabs}
        activeTab={tab}
        onTabChange={setTab}
      />
      <LegendPanel layers={data.layers} layerState={layerState} />
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
