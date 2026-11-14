/**
 * Top-left title card plus a badge telling where the backend gets its
 * data: Earth mode (remote NASA APIs) or Mars mode (local, offline).
 */
export default function Header({ health }) {
  const isLocal = health?.dataSource === 'local'
  return (
    <header className="hud header">
      <h1>Arturo</h1>
      <p className="muted">Interplanetary Survival Guide · Martian Map</p>
      <span
        className={`badge ${isLocal ? 'badge-mars' : 'badge-earth'}`}
        title={health?.tileProvider}
      >
        {isLocal ? 'Mars mode · local data' : 'Earth mode · NASA APIs'}
      </span>
    </header>
  )
}
