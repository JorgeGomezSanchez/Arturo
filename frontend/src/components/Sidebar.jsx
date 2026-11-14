import { useState } from 'react'

/**
 * Left sidebar: title card + tabbed panel. Tabs are big buttons (touch
 * friendly) and the whole sidebar can be collapsed to free the map on
 * small screens.
 *
 * tabs = [{ id, label, badge?, content }]
 * autoCollapse: when it turns true on a phone (e.g. a route is being
 * drawn), the sidebar folds away so the map can be tapped.
 */
export default function Sidebar({ header, tabs, activeTab, onTabChange, autoCollapse = false }) {
  // Start collapsed on phones so the map is visible first.
  const [collapsed, setCollapsed] = useState(
    () => typeof window !== 'undefined' && window.matchMedia?.('(max-width: 700px)').matches,
  )
  // Fold on the rising edge of autoCollapse (state adjusted during render).
  const [prevAuto, setPrevAuto] = useState(autoCollapse)
  if (autoCollapse !== prevAuto) {
    setPrevAuto(autoCollapse)
    if (autoCollapse && window.matchMedia?.('(max-width: 700px)').matches) setCollapsed(true)
  }
  const current = tabs.find((t) => t.id === activeTab) ?? tabs[0]
  return (
    <div className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      {header}
      <div className="hud tab-panel">
        <div className="tabs" role="tablist">
          {tabs.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={!collapsed && t.id === current.id}
              className={`tab ${!collapsed && t.id === current.id ? 'active' : ''}`}
              onClick={() => {
                setCollapsed(false)
                onTabChange(t.id)
              }}
            >
              {t.label}
              {t.badge ? <span className="tab-badge">{t.badge}</span> : null}
            </button>
          ))}
          <button
            className="tab collapse"
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? 'Expand panel' : 'Collapse panel'}
            title={collapsed ? 'Expand panel' : 'Collapse panel'}
          >
            {collapsed ? '▸' : '◂'}
          </button>
        </div>
        {!collapsed && <div className="tab-content">{current.content}</div>}
      </div>
    </div>
  )
}
