import { useState, useEffect, useRef } from 'react'

const API_BASE = ''

function buildCamBase(ip) {
  if (!ip || ip.trim() === '') return '/cam'
  return `http://${ip.trim()}:5000`
}
const CLASSES = ['pass', 'fail', 'null']
const CLASS_COLORS = { pass: '#4ade80', fail: '#f87171', null: '#94a3b8' }

function DebugFeed({ active, camBase }) {
  return (
    <img
      src={active ? `${camBase}/video_feed` : undefined}
      alt="Live camera feed"
      className="debug-cam-img"
      style={{ opacity: active ? 1 : 0.15 }}
    />
  )
}

function LiveTab({ cameraActive, camBase, debugModels, debugSelectedModel, setDebugSelectedModel, debugScores, setDebugScores, debugStatus, snapClass, setSnapClass, saveSnapshot, snapStatus, saving, refreshModels }) {
  return (
    <div className="debugger-panel">
      <div className="debugger-feed-wrap">
        <DebugFeed active={cameraActive} camBase={camBase} />
        <div className="debugger-snap-bar">
          <select className="flag-select" value={snapClass} onChange={e => setSnapClass(e.target.value)}>
            {CLASSES.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          <button className="btn-register" onClick={saveSnapshot} disabled={saving} style={{ opacity: saving ? 0.6 : 1 }}>
            {saving ? 'Saving...' : 'Save Snapshot'}
          </button>
          {snapStatus && <span className={`status-msg ${snapStatus.type}`} style={{ fontSize: 11 }}>{snapStatus.message}</span>}
        </div>
      </div>
      <div className="debugger-sidebar">
        <div className="debugger-controls">
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <label className="debugger-label">Model</label>
            <button className="btn-register" style={{ marginLeft: 'auto', padding: '2px 8px', fontSize: 11 }} onClick={refreshModels}>↻</button>
          </div>
          <select
            className="debugger-select"
            value={debugSelectedModel}
            onChange={e => { setDebugScores([]); setDebugSelectedModel(e.target.value) }}
          >
            {debugModels.map(m => (
              <option key={m} value={m}>{m.replace('models/', '')}</option>
            ))}
            {debugModels.length === 0 && <option disabled>Loading models...</option>}
          </select>
        </div>

        <div className="debugger-scores-title">Confidence Scores</div>
        <div className="debugger-score-list">
          {debugScores.map((item, i) => {
            const pct = Math.round(item.score * 100)
            const isTop = i === 0
            const cls = item.name.includes('pass') ? 'pass' : item.name.includes('fail') ? 'fail' : 'null'
            const color = isTop ? CLASS_COLORS[cls] : '#334155'
            return (
              <div key={item.name} className="debugger-score-row">
                <div className="debugger-score-meta">
                  <span className="debugger-class-name">{item.name}</span>
                  <span className="debugger-pct" style={{ color: isTop ? color : '#64748b' }}>{pct}%</span>
                </div>
                <div className="debugger-bar-bg">
                  <div className="debugger-bar-fill" style={{ width: `${pct}%`, background: color }} />
                </div>
              </div>
            )
          })}
          {debugScores.length === 0 && (
            <p className="status-msg" style={{ marginTop: 16 }}>Waiting for camera server...</p>
          )}
        </div>

        {debugScores.length > 0 && (() => {
          const top = debugScores[0]
          const pct = Math.round(top.score * 100)
          const cls = top.name.includes('pass') ? 'pass' : top.name.includes('fail') ? 'fail' : 'null'
          return (
            <div className={`debugger-top-result debugger-result-${cls}`}>
              {top.name.toUpperCase()}&nbsp;&nbsp;{pct}%
            </div>
          )
        })()}

        <div className="debugger-status">{debugStatus}</div>
      </div>
    </div>
  )
}

function CropEditor({ cls, filename, onSaved, onClose }) {
  const canvasRef  = useRef(null)
  const imgRef     = useRef(null)
  const dragRef    = useRef(null)   // {startX, startY} — ref so mousemove doesn't re-render
  const boxRef     = useRef(null)   // current box in canvas px — ref for same reason
  const hintRef    = useRef(null)   // DOM span — updated directly to avoid re-renders during drag
  const [box, setBox]       = useState(null)   // synced after mouseup for save button
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState(null)

  const srcRef = useRef(`/dataset-images/${cls}/${encodeURIComponent(filename)}?t=${Date.now()}`)

  const draw = () => {
    const canvas = canvasRef.current
    const img    = imgRef.current
    if (!canvas || !img || !img.complete || img.naturalWidth === 0) return
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
    const b = boxRef.current
    if (b && b.w > 1 && b.h > 1) {
      const { x, y, w, h } = b
      ctx.fillStyle = 'rgba(0,0,0,0.55)'
      ctx.fillRect(0,     0,     canvas.width, y)
      ctx.fillRect(0,     y + h, canvas.width, canvas.height - y - h)
      ctx.fillRect(0,     y,     x,            h)
      ctx.fillRect(x + w, y,     canvas.width - x - w, h)
      ctx.strokeStyle = '#ffffff'
      ctx.lineWidth   = 1
      ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1)
      ctx.strokeStyle = '#818cf8'
      ctx.lineWidth   = 1.5
      ctx.setLineDash([])
      ctx.strokeRect(x, y, w, h)
      ctx.strokeStyle = 'rgba(255,255,255,0.25)'
      ctx.lineWidth   = 0.5
      ;[1/3, 2/3].forEach(f => {
        ctx.beginPath(); ctx.moveTo(x + w * f, y); ctx.lineTo(x + w * f, y + h); ctx.stroke()
        ctx.beginPath(); ctx.moveTo(x, y + h * f); ctx.lineTo(x + w, y + h * f); ctx.stroke()
      })
      ctx.fillStyle = '#818cf8'
      ;[[x,y],[x+w,y],[x,y+h],[x+w,y+h]].forEach(([hx,hy]) => {
        ctx.fillRect(hx - 4, hy - 4, 8, 8)
      })
    }
  }

  // Draw image as soon as it loads
  useEffect(() => {
    const img = imgRef.current
    if (!img) return
    img.src = srcRef.current
    img.onload = () => draw()
  }, [])

  const HANDLE_R = 7  // hit-test radius for corner handles

  const canvasCoords = e => {
    const r = canvasRef.current.getBoundingClientRect()
    const scaleX = canvasRef.current.width  / r.width
    const scaleY = canvasRef.current.height / r.height
    return { cx: (e.clientX - r.left) * scaleX, cy: (e.clientY - r.top) * scaleY }
  }

  // Returns 'tl'|'tr'|'bl'|'br' if near a corner, 'move' if inside box, else null
  const hitTest = (cx, cy) => {
    const b = boxRef.current
    if (!b) return null
    const { x, y, w, h } = b
    const corners = { tl: [x, y], tr: [x+w, y], bl: [x, y+h], br: [x+w, y+h] }
    for (const [name, [hx, hy]] of Object.entries(corners)) {
      if (Math.abs(cx - hx) <= HANDLE_R && Math.abs(cy - hy) <= HANDLE_R) return name
    }
    if (cx >= x && cx <= x+w && cy >= y && cy <= y+h) return 'move'
    return null
  }

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))

  const onMouseDown = e => {
    e.preventDefault()
    const { cx, cy } = canvasCoords(e)
    const hit = hitTest(cx, cy)
    if (hit) {
      // dragging existing box — store mode + snapshot of box at drag start
      dragRef.current = { mode: hit, ox: cx, oy: cy, snap: { ...boxRef.current } }
    } else {
      // drawing new box
      dragRef.current = { mode: 'draw', startX: cx, startY: cy }
      boxRef.current  = null
      setBox(null)
    }
    setStatus(null)
  }

  const onMouseMove = e => {
    const canvas = canvasRef.current
    const { cx, cy } = canvasCoords(e)

    // Update cursor based on hover
    if (!dragRef.current) {
      const hit = hitTest(cx, cy)
      canvas.style.cursor =
        hit === 'tl' || hit === 'br' ? 'nwse-resize' :
        hit === 'tr' || hit === 'bl' ? 'nesw-resize' :
        hit === 'move' ? 'move' : 'crosshair'
      return
    }

    const { mode, ox, oy, snap, startX, startY } = dragRef.current
    const cw = canvas.width, ch = canvas.height

    if (mode === 'draw') {
      const rawW = cx - startX, rawH = cy - startY
      const side = Math.min(Math.abs(rawW), Math.abs(rawH))
      const x = rawW >= 0 ? startX : Math.max(0, startX - side)
      const y = rawH >= 0 ? startY : Math.max(0, startY - side)
      const w = Math.min(side, cw - x)
      const h = Math.min(side, ch - y)
      boxRef.current = { x, y, w, h }
    } else if (mode === 'move') {
      const dx = cx - ox, dy = cy - oy
      const x = clamp(snap.x + dx, 0, cw - snap.w)
      const y = clamp(snap.y + dy, 0, ch - snap.h)
      boxRef.current = { x, y, w: snap.w, h: snap.h }
    } else {
      // corner resize — keep opposite corner fixed, enforce square
      const dx = cx - ox, dy = cy - oy
      let { x, y, w, h } = snap
      let nx = x, ny = y, nw = w

      if (mode === 'br') { nw = clamp(w + Math.max(dx, dy), 4, Math.min(cw - x, ch - y)) }
      if (mode === 'tl') { const d = Math.max(-dx, -dy); nw = clamp(w + d, 4, Math.min(x + w, y + h)); nx = x + w - nw; ny = y + h - nw }
      if (mode === 'tr') { const d = Math.max(dx, -dy);  nw = clamp(w + d, 4, Math.min(cw - x, y + h)); ny = y + h - nw }
      if (mode === 'bl') { const d = Math.max(-dx, dy);  nw = clamp(w + d, 4, Math.min(x + w, ch - y)); nx = x + w - nw }

      boxRef.current = { x: clamp(nx, 0, cw), y: clamp(ny, 0, ch), w: nw, h: nw }
    }

    draw()
    const b = boxRef.current
    if (hintRef.current && b) hintRef.current.textContent = `${Math.round(b.w)}×${Math.round(b.h)} px → saved as 224×224`
  }

  const onMouseUp = () => {
    dragRef.current = null
    setBox(boxRef.current)
  }

  const handleSave = async () => {
    if (!box || box.w < 4 || box.h < 4) return
    const canvas = canvasRef.current
    const frac = {
      x: box.x / canvas.width,
      y: box.y / canvas.height,
      w: box.w / canvas.width,
      h: box.h / canvas.height,
    }
    setSaving(true)
    try {
      const res = await fetch(`${API_BASE}/api/dataset/${cls}/${encodeURIComponent(filename)}/crop`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(frac),
      })
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`)
      setStatus({ ok: true, msg: 'Saved' })
      setBox(null)
      boxRef.current = null
      // Reload the canvas image with a cache-bust so it shows the cropped result
      const img = imgRef.current
      if (img) {
        img.onload = () => draw()
        img.src = `/dataset-images/${cls}/${encodeURIComponent(filename)}?t=${Date.now()}`
      }
      onSaved(filename)
    } catch (err) {
      setStatus({ ok: false, msg: err.message })
    } finally {
      setSaving(false)
    }
  }

  const CANVAS_SIZE = 260

  return (
    <div className="crop-editor">
      <div className="crop-editor-header">
        <span className="crop-editor-filename">{filename}</span>
        <button className="dataset-delete-btn" style={{ position: 'static', opacity: 1, fontSize: 12, padding: '2px 8px' }} onClick={onClose}>✕</button>
      </div>
      <div className="crop-canvas-wrap">
        {/* hidden img — src is set by useEffect so the onload fires after canvas mounts */}
        <img ref={imgRef} style={{ display: 'none' }} alt="" />
        <canvas
          ref={canvasRef}
          width={CANVAS_SIZE}
          height={CANVAS_SIZE}
          className="crop-canvas"
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onMouseLeave={onMouseUp}
        />
      </div>
      <div className="crop-editor-footer">
        <span className="crop-editor-hint" ref={hintRef}>Drag to set crop area</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {status && <span style={{ fontSize: 11, color: status.ok ? '#4ade80' : '#f87171' }}>{status.msg}</span>}
          <button
            className="btn-register crop-confirm-btn"
            onClick={handleSave}
            disabled={!box || box.w < 4 || box.h < 4 || saving}
          >
            {saving ? 'Saving…' : '✓ Confirm Crop'}
          </button>
        </div>
      </div>
    </div>
  )
}

function DatasetTab({ refreshKey }) {
  const [dataset, setDataset]       = useState({ pass: [], fail: [], null: [] })
  const [loading, setLoading]       = useState(true)
  const [activeClass, setActiveClass] = useState('pass')
  const [cropTarget, setCropTarget] = useState(null)  // { cls, filename }
  const [imgBust, setImgBust]       = useState({})    // { filename: timestamp } for cache-busting

  const fetchDataset = async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/dataset`)
      if (res.ok) setDataset(await res.json())
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchDataset() }, [refreshKey])

  const handleDelete = async (cls, filename) => {
    if (!window.confirm(`Remove ${filename} from ${cls}?`)) return
    const res = await fetch(`${API_BASE}/api/dataset/${cls}/${encodeURIComponent(filename)}`, { method: 'DELETE' })
    if (res.ok) {
      setDataset(prev => ({ ...prev, [cls]: prev[cls].filter(f => f !== filename) }))
      if (cropTarget?.filename === filename) setCropTarget(null)
    } else {
      alert('Delete failed')
    }
  }

  const total = CLASSES.reduce((s, c) => s + (dataset[c]?.length ?? 0), 0)
  const files = dataset[activeClass] ?? []

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="dataset-tab-bar">
        {CLASSES.map(cls => (
          <button
            key={cls}
            className={`dataset-class-btn dataset-class-btn-${cls}${activeClass === cls ? ' active' : ''}`}
            onClick={() => { setActiveClass(cls); setCropTarget(null) }}
          >
            {cls}
            <span className="dataset-class-count">{dataset[cls]?.length ?? 0}</span>
          </button>
        ))}
        <span className="dataset-total">Total: {total}</span>
        <button className="btn-register" style={{ marginLeft: 'auto' }} onClick={fetchDataset}>Refresh</button>
      </div>

      <div className="dataset-body">
        <div className="dataset-grid-wrap">
          {loading
            ? <p className="status-msg" style={{ margin: 16 }}>Loading...</p>
            : files.length === 0
              ? <p className="status-msg" style={{ margin: 16 }}>No images in class "{activeClass}".</p>
              : <div className="dataset-grid">
                  {files.map(f => (
                    <div
                      key={f}
                      className={`dataset-item${cropTarget?.filename === f ? ' crop-selected' : ''}`}
                      onClick={() => setCropTarget({ cls: activeClass, filename: f })}
                    >
                      <img src={`/dataset-images/${activeClass}/${encodeURIComponent(f)}${imgBust[f] ? `?t=${imgBust[f]}` : ''}`} alt={f} />
                      <button className="dataset-delete-btn" onClick={e => { e.stopPropagation(); handleDelete(activeClass, f) }} title="Remove from dataset">✕</button>
                    </div>
                  ))}
                </div>
          }
        </div>

        {cropTarget && (
          <CropEditor
            key={cropTarget.filename}
            cls={cropTarget.cls}
            filename={cropTarget.filename}
            onSaved={(filename) => setImgBust(b => ({ ...b, [filename]: Date.now() }))}
            onClose={() => setCropTarget(null)}
          />
        )}
      </div>
    </div>
  )
}

export default function DebuggerTab() {
  const [innerTab, setInnerTab] = useState('live')

  const [camIp, setCamIp] = useState(() => localStorage.getItem('camIp') || '')
  const [camIpInput, setCamIpInput] = useState(() => localStorage.getItem('camIp') || '')
  const [camBase, setCamBase] = useState(() => buildCamBase(localStorage.getItem('camIp') || ''))
  const [testStatus, setTestStatus] = useState(null)

  const [debugModels, setDebugModels] = useState([])
  const [debugSelectedModel, setDebugSelectedModel] = useState('')
  const [debugScores, setDebugScores] = useState([])
  const [debugStatus, setDebugStatus] = useState('Waiting...')
  const [cameraActive, setCameraActive] = useState(true)
  const [snapClass, setSnapClass] = useState('pass')
  const [snapStatus, setSnapStatus] = useState(null)
  const [saving, setSaving] = useState(false)
  const [datasetRefreshKey, setDatasetRefreshKey] = useState(0)
  const smoothedScores = useRef({})
  const EMA_ALPHA = 0.25

  const applyIp = (ip) => {
    const trimmed = ip.trim()
    localStorage.setItem('camIp', trimmed)
    setCamIp(trimmed)
    setCamBase(buildCamBase(trimmed))
    setDebugScores([])
    smoothedScores.current = {}
    setDebugStatus('Waiting...')
    setDebugModels([])
    setTestStatus(null)
  }

  const testConnection = async () => {
    setTestStatus({ type: 'info', message: 'Testing...' })
    const base = buildCamBase(camIpInput)
    try {
      const res = await fetch(`${base}/api/camera/status`)
      if (res.ok) {
        const json = await res.json()
        setTestStatus({ type: 'success', message: `Connected · camera ${json.active ? 'active' : 'inactive'}` })
      } else {
        setTestStatus({ type: 'error', message: `HTTP ${res.status}` })
      }
    } catch {
      setTestStatus({ type: 'error', message: 'Unreachable' })
    }
  }

  const refreshModels = async () => {
    try {
      const res = await fetch(`${camBase}/api/models`)
      if (res.ok) {
        const models = await res.json()
        setDebugModels(models)
        if (!models.includes(debugSelectedModel)) {
          const preferred = models.find(m => m.includes('tflite_1000'))
          setDebugSelectedModel(preferred ?? models[0] ?? '')
        }
      }
    } catch {
      setDebugStatus('Camera server unreachable')
    }
  }

  useEffect(() => {
    const init = async () => {
      try {
        const [modelsRes, statusRes] = await Promise.all([
          fetch(`${camBase}/api/models`),
          fetch(`${camBase}/api/camera/status`),
        ])
        if (modelsRes.ok) {
          const models = await modelsRes.json()
          setDebugModels(models)
          const preferred = models.find(m => m.includes('tflite_1000'))
          setDebugSelectedModel(preferred ?? models[0] ?? '')
        }
        if (statusRes.ok) {
          const s = await statusRes.json()
          setCameraActive(s.active)
        }
      } catch {
        setDebugStatus('Camera server unreachable')
      }
    }
    init()
  }, [camBase])

  const toggleCamera = async () => {
    try {
      const res = await fetch(`${camBase}/api/camera/toggle`, { method: 'POST' })
      const json = await res.json()
      setCameraActive(json.active)
      setDebugScores([])
      smoothedScores.current = {}
      setDebugStatus(json.active ? 'Camera on' : 'Camera off')
    } catch {
      setDebugStatus('Camera server unreachable')
    }
  }

  useEffect(() => {
    smoothedScores.current = {}
    const id = setInterval(async () => {
      if (!debugSelectedModel || !cameraActive || innerTab !== 'live') return
      try {
        const res = await fetch(`${camBase}/api/classify?model=${encodeURIComponent(debugSelectedModel)}`)
        const data = await res.json()
        if (data.scores) {
          const prev = smoothedScores.current
          const blended = data.scores.map(item => {
            const raw = item.score ?? item.confidence ?? 0
            const last = prev[item.name] ?? raw
            const s = EMA_ALPHA * raw + (1 - EMA_ALPHA) * last
            prev[item.name] = s
            return { ...item, score: s }
          })
          setDebugScores(blended)
          setDebugStatus('Live · ' + new Date().toLocaleTimeString())
        } else {
          setDebugStatus(data.error ?? 'Unknown error')
        }
      } catch {
        setDebugStatus('Camera server unreachable')
      }
    }, 150)
    return () => clearInterval(id)
  }, [debugSelectedModel, innerTab, camBase])

  const saveSnapshot = async () => {
    setSnapStatus(null)
    setSaving(true)
    try {
      const res = await fetch(`/api/dataset/${snapClass}/save-frame`, { method: 'POST' })
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`)
      setSnapStatus({ type: 'success', message: json.message })
      setDatasetRefreshKey(k => k + 1)
    } catch (err) {
      setSnapStatus({ type: 'error', message: err.message })
    } finally {
      setSaving(false)
    }
    setTimeout(() => setSnapStatus(null), 3000)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="debugger-inner-tabs">
        <button className={`debugger-inner-tab${innerTab === 'live' ? ' active' : ''}`} onClick={() => setInnerTab('live')}>Live Feed</button>
        <button className={`debugger-inner-tab${innerTab === 'dataset' ? ' active' : ''}`} onClick={() => setInnerTab('dataset')}>Dataset</button>
        <button className={`debugger-inner-tab${innerTab === 'settings' ? ' active' : ''}`} onClick={() => setInnerTab('settings')}>Settings</button>
        <div className="debugger-tab-actions">
          <button
            className={`debug-menu-btn${cameraActive ? '' : ' active'}`}
            onClick={toggleCamera}
          >
            {cameraActive ? '⏹ Release Camera' : '▶ Enable Camera'}
          </button>
        </div>
      </div>

      <div style={{ flex: 1, overflow: 'hidden' }}>
        {innerTab === 'live' && (
          <LiveTab
            cameraActive={cameraActive}
            camBase={camBase}
            snapClass={snapClass}
            setSnapClass={setSnapClass}
            saveSnapshot={saveSnapshot}
            snapStatus={snapStatus}
            saving={saving}
            debugModels={debugModels}
            debugSelectedModel={debugSelectedModel}
            setDebugSelectedModel={setDebugSelectedModel}
            debugScores={debugScores}
            setDebugScores={setDebugScores}
            debugStatus={debugStatus}
            refreshModels={refreshModels}
          />
        )}
        {innerTab === 'dataset' && <DatasetTab refreshKey={datasetRefreshKey} />}
        {innerTab === 'settings' && (
          <div className="debugger-settings">
            <div className="debugger-settings-group">
              <h3 className="debugger-settings-title">Camera Server</h3>
              <p className="debugger-settings-desc">
                Leave blank to use the local proxy. Enter an IP to connect directly to a remote camera server.
              </p>
              <div className="debugger-settings-row">
                <label className="debugger-label">IP Address</label>
                <div className="debugger-settings-input-wrap">
                  <span className="debugger-settings-prefix">http://</span>
                  <input
                    className="debugger-select"
                    style={{ flex: 1, fontFamily: 'monospace' }}
                    placeholder="e.g. 192.168.3.115"
                    value={camIpInput}
                    onChange={e => setCamIpInput(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && applyIp(camIpInput)}
                  />
                  <span className="debugger-settings-suffix">:5000</span>
                </div>
              </div>
              <div className="debugger-settings-actions">
                <button className="btn-register" onClick={testConnection}>Test</button>
                <button
                  className="btn-register"
                  style={{ background: '#1e1b4b', borderColor: '#4f46e5', color: '#a5b4fc' }}
                  onClick={() => applyIp(camIpInput)}
                >
                  Apply
                </button>
                {camIp && (
                  <button className="btn-cancel" onClick={() => { setCamIpInput(''); applyIp('') }}>
                    Clear (use proxy)
                  </button>
                )}
              </div>
              {testStatus && (
                <p className={`status-msg ${testStatus.type}`} style={{ marginTop: 8 }}>{testStatus.message}</p>
              )}
              {camIp && (
                <p className="debugger-settings-desc" style={{ marginTop: 8 }}>
                  Active: <span style={{ color: '#a5b4fc', fontFamily: 'monospace' }}>http://{camIp}:5000</span>
                </p>
              )}
              {!camIp && (
                <p className="debugger-settings-desc" style={{ marginTop: 8 }}>
                  Active: <span style={{ color: '#64748b', fontFamily: 'monospace' }}>/cam (local proxy)</span>
                </p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
