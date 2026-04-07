import { useState, useEffect, useRef, useCallback } from 'react'
import './App.css'
import { API_BASE } from './constants.js'
import ShipsTab      from './components/ShipsTab.jsx'
import PartsTab      from './components/PartsTab.jsx'
import CustomersTab  from './components/CustomersTab.jsx'
import OrdersTab     from './components/OrdersTab.jsx'
import SnapshotsTab  from './components/SnapshotsTab.jsx'
import DebuggerTab   from './components/DebuggerTab.jsx'
import TrainModal    from './components/TrainModal.jsx'

function App() {
  const [data, setData]       = useState({ ships: [], parts: [], customers: [] })
  const [orders, setOrders]   = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)
  const [activeTab, setActiveTab] = useState('orders')
  const [showTrain, setShowTrain] = useState(false)
  const [wsConnected, setWsConnected] = useState(false)
  const wsRef = useRef(null)
  const reconnectTimer = useRef(null)

  const switchTab = (key) => setActiveTab(key)

  const refreshData = useCallback(async () => {
    const res = await fetch(`${API_BASE}/api/init-data`)
    if (res.ok) setData(await res.json())
  }, [])

  const refreshOrders = useCallback(async () => {
    const res = await fetch(`${API_BASE}/api/orders`)
    if (res.ok) setOrders(await res.json())
  }, [])

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/init-data`).then(r => r.json()),
      fetch(`${API_BASE}/api/orders`).then(r => r.json()),
    ])
      .then(([initJson, ordersJson]) => {
        setData(initJson)
        setOrders(ordersJson)
        setLoading(false)
      })
      .catch(err => {
        setError(err.message)
        setLoading(false)
      })
  }, [])

  useEffect(() => {
    const WS_URL = `ws://${window.location.host}/ws/orders`

    const connect = () => {
      const ws = new WebSocket(WS_URL)
      wsRef.current = ws

      ws.onopen = () => {
        setWsConnected(true)
        clearTimeout(reconnectTimer.current)
      }

      ws.onmessage = async (e) => {
        try {
          const event = JSON.parse(e.data)
          if (['order_created', 'order_updated', 'order_deleted'].includes(event.event)) {
            await refreshOrders()
            await refreshData()
          }
        } catch {}
      }

      ws.onclose = () => {
        setWsConnected(false)
        reconnectTimer.current = setTimeout(connect, 3000)
      }

      ws.onerror = () => ws.close()
    }

    connect()

    return () => {
      clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [refreshOrders, refreshData])

  const TABS = [
    { key: 'ships',     label: 'Ships',     value: data.ships.length },
    { key: 'parts',     label: 'Parts',     value: data.parts.length },
    { key: 'customers', label: 'Customers', value: data.customers.length },
    { key: 'orders',    label: 'Orders',    value: orders.length },
    { key: 'snapshots', label: 'Snapshots', value: '…' },
  ]

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <h1>SF Dashboard</h1>
        <span className="subtitle">Smart Factory Operations</span>
        <span className={`ws-indicator ${wsConnected ? 'ws-connected' : 'ws-disconnected'}`}>
          {wsConnected ? 'Live' : 'Reconnecting...'}
        </span>
        <button
          className={`debug-menu-btn${activeTab === 'debugger' ? ' active' : ''}`}
          onClick={() => switchTab(activeTab === 'debugger' ? 'orders' : 'debugger')}
        >
          {activeTab === 'debugger' ? '✕ Close Debugger' : '⚙ Model Debugger'}
        </button>
        <button className="debug-menu-btn" onClick={() => setShowTrain(true)}>
          ▶ Retrain Model
        </button>
      </header>

      {!loading && !error && (
        <div className="stats-bar">
          {TABS.map(tab => (
            <div
              key={tab.key}
              className={`stat-card${activeTab === tab.key ? ' active' : ''}`}
              onClick={() => switchTab(tab.key)}
            >
              <div className="stat-value">{tab.value}</div>
              <div className="stat-label">{tab.label}</div>
            </div>
          ))}
        </div>
      )}

      {loading && <p className="status-msg" style={{ margin: '24px' }}>Loading data...</p>}
      {error   && <p className="status-msg error" style={{ margin: '24px' }}>Failed to connect to API: {error}</p>}

      {!loading && !error && (
        <div className="tab-content">
          {activeTab === 'ships'     && <ShipsTab     ships={data.ships}         onRefresh={refreshData} />}
          {activeTab === 'parts'     && <PartsTab     parts={data.parts}         onRefresh={refreshData} />}
          {activeTab === 'customers' && <CustomersTab customers={data.customers} onRefresh={refreshData} />}
          {activeTab === 'orders'    && (
            <OrdersTab
              orders={orders}
              parts={data.parts}
              customers={data.customers}
              onRefreshOrders={refreshOrders}
              onRefreshData={refreshData}
            />
          )}
          {activeTab === 'snapshots' && <SnapshotsTab />}
          {activeTab === 'debugger'  && <DebuggerTab />}
        </div>
      )}

      <TrainModal show={showTrain} onClose={() => setShowTrain(false)} />
    </div>
  )
}

export default App
