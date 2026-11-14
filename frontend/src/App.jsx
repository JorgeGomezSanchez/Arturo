import MarsMap from './components/MarsMap'
import { useBackendData } from './hooks/useBackendData'
import './App.css'

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

  return (
    <div className="app">
      <MarsMap mapConfig={data.mapConfig} layers={data.layers} />
    </div>
  )
}
