import { useState, useEffect, useRef } from 'react'

const API_BASE = ''

const DEFAULTS = {
  epochs:      50,
  lr:          0.001,
  batch_size:  16,
  dense_units: 128,
  alpha:       0.35,
  val_split:   0.15,
  augment:       false,
  aug_intensity: 1.0,
  optimizer:     'adam',
  momentum:      0.0,
}

function parseMetrics(log) {
  const points = []
  for (const rawLine of log) {
    const line = rawLine.includes('\r') ? rawLine.split('\r').pop() : rawLine
    const lossM    = line.match(/(?<![a-z_])loss:\s*([\d.]+)/i)
    const accM     = line.match(/(?<![a-z_])accuracy:\s*([\d.]+)/i)
    const valLossM = line.match(/val_loss:\s*([\d.]+)/i)
    const valAccM  = line.match(/val_accuracy:\s*([\d.]+)/i)
    if (lossM && accM && valLossM && valAccM) {
      points.push({
        loss:    parseFloat(lossM[1]),
        acc:     parseFloat(accM[1]),
        valLoss: parseFloat(valLossM[1]),
        valAcc:  parseFloat(valAccM[1]),
      })
    }
  }
  return points
}

function MiniChart({ points, yKey1, yKey2, label1, label2, title, color1, color2, yFixed }) {
  const W = 280, H = 120
  const PAD = { top: 8, right: 10, bottom: 22, left: 36 }
  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom

  const isEmpty = points.length < 2
  const vals1 = points.map(p => p[yKey1])
  const vals2 = points.map(p => p[yKey2])
  const all   = [...vals1, ...vals2]
  
  const yMin  = yFixed ? 0 : Math.max(0, Math.min(...all) - 0.05)
  const yMax  = yFixed ? 1 : Math.max(...all) + 0.05
  const yRange = yMax - yMin || 1

  // --- SUBDIVISION LOGIC ---
  // Generate 5 Y-axis ticks instead of 3 for better resolution
  const yTickCount = 5;
  const yTicks = Array.from({ length: yTickCount }, (_, i) => yMin + (i * (yRange / (yTickCount - 1))));

  // Generate X-axis subdivisions (every 10 epochs if possible)
  const xTickStep = points.length > 20 ? 10 : 5;
  const xTicks = [];
  if (points.length > 1) {
    for (let i = 0; i < points.length; i += xTickStep) xTicks.push(i);
    if (xTicks[xTicks.length - 1] !== points.length - 1) xTicks.push(points.length - 1);
  }
  // -------------------------

  const xScale = i => PAD.left + (points.length > 1 ? (i / (points.length - 1)) * innerW : 0)
  const yScale = v => PAD.top + (1 - (v - yMin) / yRange) * innerH

  const polyPts = key => points.map((p, i) => `${xScale(i)},${yScale(p[key])}`).join(' ')
  const fillPts = key => {
    if (points.length < 2) return ''
    const line = points.map((p, i) => `${xScale(i)},${yScale(p[key])}`).join(' ')
    return `${PAD.left},${yScale(yMin)} ${line} ${xScale(points.length - 1)},${yScale(yMin)}`
  }

  const lastV1 = vals1[vals1.length - 1]
  const lastV2 = vals2[vals2.length - 1]

  return (
    <div className="train-chart-box">
      <div className="train-chart-title">{title}</div>
      <svg width={W} height={H}>
        {/* Y-Axis Grid Lines & Labels */}
        {yTicks.map((v, i) => (
          <g key={`y-${i}`}>
            <line 
              x1={PAD.left} y1={yScale(v)} 
              x2={W - PAD.right} y2={yScale(v)} 
              stroke="#1a2030" 
              strokeWidth={i === 0 ? "2" : "1"} // Base line is thicker
              strokeDasharray={i === 0 ? "0" : "2,2"} // Dash internal lines
            />
            <text x={PAD.left - 4} y={yScale(v) + 3} textAnchor="end" fill="#3d4f6a" fontSize="8">{v.toFixed(2)}</text>
          </g>
        ))}

        {/* X-Axis Vertical Subdivisions */}
        {!isEmpty && xTicks.map((epochIdx, i) => (
          <g key={`x-${i}`}>
            <line 
              x1={xScale(epochIdx)} y1={PAD.top} 
              x2={xScale(epochIdx)} y2={PAD.top + innerH} 
              stroke="#1a2030" strokeWidth="1" strokeDasharray="2,2" 
            />
            <text x={xScale(epochIdx)} y={H - 4} fill="#3d4f6a" fontSize="8" textAnchor="middle">{epochIdx + 1}</text>
          </g>
        ))}

        {/* Main Axes */}
        <line x1={PAD.left} y1={PAD.top} x2={PAD.left} y2={PAD.top + innerH} stroke="#2d3a50" strokeWidth="1" />
        <line x1={PAD.left} y1={PAD.top + innerH} x2={W - PAD.right} y2={PAD.top + innerH} stroke="#2d3a50" strokeWidth="1" />
        
        {!isEmpty && <>
          <polygon points={fillPts(yKey1)} fill={color1} fillOpacity="0.08" />
          <polygon points={fillPts(yKey2)} fill={color2} fillOpacity="0.06" />
          <polyline points={polyPts(yKey1)} fill="none" stroke={color1} strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" />
          <polyline points={polyPts(yKey2)} fill="none" stroke={color2} strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" strokeDasharray="5,3" />
          <circle cx={xScale(points.length - 1)} cy={yScale(lastV1)} r="3" fill={color1} />
          <circle cx={xScale(points.length - 1)} cy={yScale(lastV2)} r="3" fill={color2} />
        </>}
        
        {isEmpty && (
          <text x={W / 2} y={H / 2} textAnchor="middle" fill="#1e2a3a" fontSize="11" fontStyle="italic">Waiting for data…</text>
        )}
      </svg>
      <div className="train-chart-legend">
        {!isEmpty && <>
          <span style={{ color: color1 }}>&#8212; {label1}: {lastV1?.toFixed(3)}</span>
          <span style={{ color: color2 }}>&#8213;&#8213; {label2}: {lastV2?.toFixed(3)}</span>
        </>}
      </div>
    </div>
  )
}

const TIPS = {
  epochs:      'One epoch = one full pass through all training images. More epochs let the model converge further, but too many can overfit.',
  lr:          'How large each weight update step is. Lower values train more slowly but more stably. 0.001 is a safe default.',
  batch_size:  'Number of images processed before each weight update. Smaller batches add noise (can help generalisation); larger batches are faster.',
  dense_units: 'Width of the classification head layer. More units = more capacity to learn complex patterns, but also more risk of overfitting.',
  alpha:       'MobileNetV2 width multiplier. Smaller values = fewer filters = faster inference. Only affects the fallback backbone (not the TM backbone).',
  val_split:   'Fraction of images held back for validation. These are never used for training — only for measuring generalisation.',
  augment:       'Generates 3× extra training samples by applying random flips, rotations, zoom, and brightness shifts before feature extraction.',
  aug_intensity: 'Scales how aggressive the augmentation transforms are. Subtle makes very small changes; Aggressive applies large rotations, zooms, and brightness swings.',
  optimizer:   'Algorithm used to update weights. Adam is adaptive and works well by default. SGD is simpler and can generalise better with tuning. RMSprop suits noisy gradients. Adagrad adapts per-parameter.',
  momentum:    'Momentum for SGD and RMSprop — carries a fraction of the previous gradient into the next update, helping the optimizer move faster through flat regions. Ignored by Adam and Adagrad.',
}

function Tooltip({ text }) {
  const [visible, setVisible] = useState(false)
  const ref = useRef(null)
  const [above, setAbove] = useState(false)

  const show = () => {
    if (ref.current) {
      const rect = ref.current.getBoundingClientRect()
      setAbove(rect.bottom + 90 > window.innerHeight)
    }
    setVisible(true)
  }

  return (
    <span className="tip-anchor" ref={ref} onMouseEnter={show} onMouseLeave={() => setVisible(false)}>
      <span className="tip-icon">i</span>
      {visible && <span className={`tip-box ${above ? 'tip-above' : 'tip-below'}`}>{text}</span>}
    </span>
  )
}

function ConfigPanel({ cfg, setCfg, disabled, onStart, trainRunning, trainExitCode }) {
  const sel = (key, options) => (
    <select
      className="train-cfg-input"
      value={cfg[key]}
      disabled={disabled}
      onChange={e => setCfg(p => ({ ...p, [key]: parseFloat(e.target.value) }))}
    >
      {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  )

  const btnLabel = trainRunning
    ? 'Training…'
    : trainExitCode !== null
      ? 'Retrain'
      : 'Start Training'

  return (
    <div className="train-config">
      <div className="train-cfg-grid">
        <div className="train-cfg-field">
          <div className="train-cfg-label">Epochs <Tooltip text={TIPS.epochs} /></div>
          <input
            type="number" className="train-cfg-input"
            value={cfg.epochs} min={1} max={500} step={1}
            disabled={disabled}
            onChange={e => setCfg(p => ({ ...p, epochs: parseInt(e.target.value) || p.epochs }))}
          />
        </div>
        <div className="train-cfg-field">
          <div className="train-cfg-label">Learning Rate <Tooltip text={TIPS.lr} /></div>
          <input
            type="number"
            className="train-cfg-input"
            value={cfg.lr}
            min={0.000001} max={1} step="any"
            disabled={disabled}
            onChange={e => { const v = parseFloat(e.target.value); if (!isNaN(v) && v > 0) setCfg(p => ({ ...p, lr: v })) }}
          />
        </div>
        <div className="train-cfg-field">
          <div className="train-cfg-label">Batch Size <Tooltip text={TIPS.batch_size} /></div>
          {sel('batch_size', [
            { value: 8,  label: '8' },
            { value: 16, label: '16' },
            { value: 32, label: '32' },
            { value: 64, label: '64' },
          ])}
        </div>
        <div className="train-cfg-field">
          <div className="train-cfg-label">Dense Units <Tooltip text={TIPS.dense_units} /></div>
          {sel('dense_units', [
            { value: 16,  label: '16' },
            { value: 32,  label: '32' },
            { value: 64,  label: '64' },
            { value: 128, label: '128' },
            { value: 256, label: '256' },
          ])}
        </div>
        <div className="train-cfg-field">
          <div className="train-cfg-label">Backbone Alpha <Tooltip text={TIPS.alpha} /></div>
          {sel('alpha', [
            { value: 0.1,  label: '0.1' },
            { value: 0.25, label: '0.25' },
            { value: 0.35, label: '0.35' },
            { value: 0.5,  label: '0.5' },
            { value: 0.75, label: '0.75' },
            { value: 1.0,  label: '1.0' },
          ])}
        </div>
        <div className="train-cfg-field">
          <div className="train-cfg-label">Val Split <Tooltip text={TIPS.val_split} /></div>
          {sel('val_split', [
            { value: 0.1,  label: '10%' },
            { value: 0.15, label: '15%' },
            { value: 0.2,  label: '20%' },
            { value: 0.25, label: '25%' },
          ])}
        </div>
        <div className="train-cfg-field">
          <div className="train-cfg-label">Optimizer <Tooltip text={TIPS.optimizer} /></div>
          <select
            className="train-cfg-input"
            value={cfg.optimizer}
            disabled={disabled}
            onChange={e => setCfg(p => ({ ...p, optimizer: e.target.value }))}
          >
            <option value="adam">Adam</option>
            <option value="sgd">SGD</option>
            <option value="rmsprop">RMSprop</option>
            <option value="adagrad">Adagrad</option>
          </select>
        </div>
        <div className="train-cfg-field" style={{ opacity: ['sgd', 'rmsprop'].includes(cfg.optimizer) ? 1 : 0.35 }}>
          <div className="train-cfg-label">Momentum <Tooltip text={TIPS.momentum} /></div>
          {sel('momentum', [
            { value: 0.0,  label: '0.0' },
            { value: 0.5,  label: '0.5' },
            { value: 0.9,  label: '0.9' },
            { value: 0.99, label: '0.99' },
          ])}
        </div>
      </div>

      <div className="train-cfg-footer">
        <label className="train-cfg-toggle">
          <input
            type="checkbox"
            checked={cfg.augment}
            disabled={disabled}
            onChange={e => setCfg(p => ({ ...p, augment: e.target.checked }))}
          />
          <span className="train-cfg-toggle-label">Data Augmentation</span>
          <Tooltip text={TIPS.augment} />
        </label>
        <label className="train-cfg-toggle" style={{ opacity: cfg.augment ? 1 : 0.35, marginLeft: 12 }}>
          <input
            type="range"
            min={0.5} max={2.0} step={0.5}
            value={cfg.aug_intensity}
            disabled={disabled || !cfg.augment}
            onChange={e => setCfg(p => ({ ...p, aug_intensity: parseFloat(e.target.value) }))}
            style={{ width: 80 }}
          />
          <span className="train-cfg-toggle-label" style={{ minWidth: 66 }}>
            {{ 0.5: 'Subtle', 1.0: 'Moderate', 1.5: 'Strong', 2.0: 'Aggressive' }[cfg.aug_intensity] ?? cfg.aug_intensity}
          </span>
          <Tooltip text={TIPS.aug_intensity} />
        </label>
        <button
          className="btn-register train-cfg-start"
          onClick={onStart}
          disabled={trainRunning}
        >
          {btnLabel}
        </button>
      </div>
    </div>
  )
}

export default function TrainModal({ show, onClose }) {
  const [cfg, setCfg]                     = useState(DEFAULTS)
  const [trainLog, setTrainLog]           = useState([])
  const [trainRunning, setTrainRunning]   = useState(false)
  const [trainExitCode, setTrainExitCode] = useState(null)
  const [hasRun, setHasRun]               = useState(false)
  const [showLog, setShowLog]             = useState(false)
  const pollRef = useRef(null)
  const logRef  = useRef(null)

  useEffect(() => {
    if (!show) clearInterval(pollRef.current)
  }, [show])

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [trainLog])

  const startTraining = async () => {
    setTrainLog([])
    setTrainExitCode(null)
    setTrainRunning(true)
    setHasRun(true)

    try {
      const res = await fetch(`${API_BASE}/api/train/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cfg),
      })
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`)
    } catch (err) {
      setTrainLog([`ERROR: ${err.message}`])
      setTrainRunning(false)
      return
    }

    pollRef.current = setInterval(async () => {
      try {
        const res  = await fetch(`${API_BASE}/api/train/status`)
        const json = await res.json()
        setTrainLog(json.log)
        setTrainRunning(json.running)
        if (!json.running) {
          setTrainExitCode(json.exit_code)
          clearInterval(pollRef.current)
        }
      } catch {}
    }, 500)
  }

  const handleClose = () => {
    if (trainRunning) return
    clearInterval(pollRef.current)
    onClose()
  }

  if (!show) return null

  const metrics = parseMetrics(trainLog)

  const statusTitle = trainRunning
    ? 'Training…'
    : trainExitCode === 0
      ? 'Done'
      : trainExitCode !== null
        ? `Failed (exit ${trainExitCode})`
        : null

  return (
    <div className="modal-overlay" onClick={handleClose}>
      <div className="modal train-modal" onClick={e => e.stopPropagation()}>
        <div className="train-modal-header">
          <h2>
            Train Model
            {statusTitle && <span className={`train-status-badge ${trainRunning ? 'running' : trainExitCode === 0 ? 'done' : 'failed'}`}>{statusTitle}</span>}
          </h2>
          <div style={{ display: 'flex', gap: 8 }}>
            {hasRun && (
              <button className="btn-cancel" onClick={() => setShowLog(v => !v)}>
                {showLog ? 'Hide Log' : 'Show Log'}
              </button>
            )}
            <button className="btn-cancel" onClick={handleClose} disabled={trainRunning}>Close</button>
          </div>
        </div>

        <ConfigPanel
          cfg={cfg}
          setCfg={setCfg}
          disabled={trainRunning}
          onStart={startTraining}
          trainRunning={trainRunning}
          trainExitCode={trainExitCode}
        />

        {hasRun && (
          <div className="train-charts">
            <MiniChart
              points={metrics} yKey1="acc" yKey2="valAcc"
              label1="train" label2="val" title="Accuracy"
              color1="#4ade80" color2="#818cf8" yFixed
            />
            <MiniChart
              points={metrics} yKey1="loss" yKey2="valLoss"
              label1="train" label2="val" title="Loss"
              color1="#f87171" color2="#fb923c"
            />
          </div>
        )}

        {hasRun && showLog && (
          <div className="train-log" ref={logRef}>
            {trainLog.length === 0 && trainRunning && (
              <span className="train-log-placeholder">Starting...</span>
            )}
            {trainLog.map((line, i) => (
              <div key={i} className={`train-log-line${line.startsWith('ERROR') ? ' train-log-error' : ''}`}>
                {line}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
