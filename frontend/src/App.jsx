import { useState } from 'react'
import Header from './components/Header'
import MarsMap from './components/MarsMap'
import ZonesPanel from './components/ZonesPanel'
import { useBackendData } from './hooks/useBackendData'
import './App.css'

export default function App() {
  const data = useBackendData()
  // Leaflet map instance, shared with panels that live outside the map.
  const [map, setMap] = useState(null)

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

  return (
    <div className="app">
      <MarsMap mapConfig={data.mapConfig} layers={data.layers} onMapReady={setMap} />
      <div className="sidebar">
        <Header health={data.health} />
        <ZonesPanel map={map} zones={data.zones} mapConfig={data.mapConfig} />
      </div>
    </div>
  )
}
