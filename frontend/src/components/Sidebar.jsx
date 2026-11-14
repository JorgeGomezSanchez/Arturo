import { useState } from 'react'

/**
 * Left sidebar: title card + tabbed panel. Tabs are big buttons (touch
 * friendly) and the whole sidebar can be collapsed to free the map on
 * small screens.
 *
 * tabs = [{ id, label, badge?, content }]
 */
export default function Sidebar({ header, tabs, activeTab, onTabChange }) {
  const [collapsed, setCollapsed] = useState(false)
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
