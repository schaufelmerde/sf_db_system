import { useState, useEffect } from 'react'

const API_BASE = ''
const PAGE_SIZE = 50

export default function SnapshotsTab() {
  const [snapshots, setSnapshots] = useState({ total: 0, items: [] })
  const [snapshotsPage, setSnapshotsPage] = useState(0)
  const [snapshotsFetching, setSnapshotsFetching] = useState(false)

  const [showEditModal, setShowEditModal] = useState(false)
  const [editingSnapshot, setEditingSnapshot] = useState(null)
  const [editForm, setEditForm] = useState({ order_id: '' })
  const [editStatus, setEditStatus] = useState(null)
  const [editSubmitting, setEditSubmitting] = useState(false)

  const [selectedSnapshots, setSelectedSnapshots] = useState(new Set())
  const [batchStatus, setBatchStatus] = useState(null)

  const fetchSnapshots = async (page = 0) => {
    setSnapshotsFetching(true)
    setSelectedSnapshots(new Set())
    try {
      const res = await fetch(`${API_BASE}/api/snapshots?limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`)
      if (res.ok) {
        setSnapshots(await res.json())
        setSnapshotsPage(page)
      }
    } finally {
      setSnapshotsFetching(false)
    }
  }

  useEffect(() => {
    fetchSnapshots(0)
  }, [])

  const openEditModal = (s) => {
    setEditingSnapshot(s)
    setEditForm({ order_id: s.order_id ?? '' })
    setEditStatus(null)
    setShowEditModal(true)
  }

  const handleEditSubmit = async e => {
    e.preventDefault()
    setEditSubmitting(true)
    setEditStatus(null)
    try {
      const res = await fetch(`${API_BASE}/api/sort-results/${editingSnapshot.result_id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ order_id: editForm.order_id || null }),
      })
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`)
      setEditStatus({ type: 'success', message: 'Updated' })
      await fetchSnapshots(snapshotsPage)
    } catch (err) {
      setEditStatus({ type: 'error', message: err.message })
    } finally {
      setEditSubmitting(false)
    }
  }

  const handleDelete = async (snapshot_id) => {
    if (!window.confirm(`Delete snapshot #${snapshot_id}?`)) return
    try {
      const res = await fetch(`${API_BASE}/api/snapshots/${snapshot_id}`, { method: 'DELETE' })
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`)
      await fetchSnapshots(snapshotsPage)
    } catch (err) {
      alert(err.message)
    }
  }

  const handleFlagSnapshot = async (snapshot_id, label) => {
    try {
      const res = await fetch(`${API_BASE}/api/snapshots/${snapshot_id}/flag`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label }),
      })
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`)
      setSnapshots(prev => ({
        ...prev,
        items: prev.items.map(s => s.snapshot_id === snapshot_id ? { ...s, dataset_label: label } : s)
      }))
      setSelectedSnapshots(prev => new Set([...prev, snapshot_id]))
    } catch (err) {
      alert(err.message)
    }
  }

  const handleUnflag = async (snapshot_id) => {
    try {
      const res = await fetch(`${API_BASE}/api/snapshots/${snapshot_id}/unflag`, { method: 'POST' })
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`)
      setSnapshots(prev => ({
        ...prev,
        items: prev.items.map(s => s.snapshot_id === snapshot_id ? { ...s, dataset_label: null } : s)
      }))
    } catch (err) {
      alert(err.message)
    }
  }

  const toggleSelect = (id) => {
    setSelectedSnapshots(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const toggleSelectAll = () => {
    setSelectedSnapshots(prev =>
      prev.size === snapshots.items.length
        ? new Set()
        : new Set(snapshots.items.map(s => s.snapshot_id))
    )
  }

  const handleBatchFlag = async () => {
    if (selectedSnapshots.size === 0) return
    setBatchStatus(null)
    try {
      const res = await fetch(`${API_BASE}/api/snapshots/batch-flag`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ snapshot_ids: [...selectedSnapshots] }),
      })
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`)
      setSelectedSnapshots(new Set())
      setBatchStatus({ type: 'success', message: json.message })
      await fetchSnapshots(snapshotsPage)
    } catch (err) {
      setBatchStatus({ type: 'error', message: err.message })
    }
  }

  const handleBatchDelete = async () => {
    if (selectedSnapshots.size === 0) return
    if (!window.confirm(`Delete ${selectedSnapshots.size} snapshot(s)?`)) return
    try {
      const res = await fetch(`${API_BASE}/api/snapshots/batch-delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ snapshot_ids: [...selectedSnapshots] }),
      })
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`)
      setSelectedSnapshots(new Set())
      await fetchSnapshots(snapshotsPage)
    } catch (err) {
      alert(err.message)
    }
  }

  return (
    <div className="panel tab-panel snapshots-panel">
      <div className="panel-header">
        <h2>Inspection Snapshots ({snapshots.total})</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {snapshotsFetching && <span className="snapshot-meta">Loading...</span>}
          <button className="btn-register" onClick={() => fetchSnapshots(snapshotsPage)}>Refresh</button>
        </div>
      </div>

      {selectedSnapshots.size > 0 && (
        <div className="batch-toolbar">
          <span className="batch-toolbar-count">{selectedSnapshots.size} selected</span>
          <button className="btn-register" onClick={handleBatchFlag}>Add to Dataset</button>
          <button className="btn-delete" style={{ opacity: 1 }} onClick={handleBatchDelete}>Delete</button>
          {batchStatus && <span className={`status-msg ${batchStatus.type}`}>{batchStatus.message}</span>}
        </div>
      )}

      <div className="snapshots-table-wrap">
        <table className="orders-table">
          <thead>
            <tr>
              <th style={{ width: 32 }}>
                <input
                  type="checkbox"
                  checked={snapshots.items.length > 0 && selectedSnapshots.size === snapshots.items.length}
                  onChange={toggleSelectAll}
                />
              </th>
              <th>Preview</th>
              <th>ID</th>
              <th>Type</th>
              <th>Order ID</th>
              <th>Result</th>
              <th>Class</th>
              <th>Conf %</th>
              <th>Taken At</th>
              <th>Retrain Class</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {snapshots.items.map(s => (
              <tr key={s.snapshot_id} style={{ background: selectedSnapshots.has(s.snapshot_id) ? '#1e1b4b' : undefined }}>
                <td>
                  <input
                    type="checkbox"
                    checked={selectedSnapshots.has(s.snapshot_id)}
                    onChange={() => toggleSelect(s.snapshot_id)}
                  />
                </td>
                <td>
                  <img
                    src={`${API_BASE}${s.url}`}
                    alt={s.snapshot_type}
                    style={{ width: 64, height: 48, objectFit: 'cover', borderRadius: 4, border: '1px solid #1e293b' }}
                  />
                </td>
                <td><span className="id">#{s.snapshot_id}</span></td>
                <td><span className="status-badge">{s.snapshot_type}</span></td>
                <td><span className="id">{s.order_id ?? '—'}</span></td>
                <td><span className={`status-badge status-${s.result_status?.toLowerCase()}`}>{s.result_status ?? '—'}</span></td>
                <td>{s.detected_class ?? '—'}</td>
                <td>{s.confidence != null ? `${s.confidence.toFixed(1)}%` : '—'}</td>
                <td className="snapshot-meta">{s.taken_at ? s.taken_at.split('.')[0] : '—'}</td>
                <td>
                  {s.dataset_label
                    ? <span className={`status-badge dataset-label-${s.dataset_label}`}>
                        {s.dataset_label}
                        <button className="btn-unflag" onClick={() => handleUnflag(s.snapshot_id)} title="Remove from dataset">✕</button>
                      </span>
                    : <select
                        className="flag-select"
                        defaultValue=""
                        onChange={e => { if (e.target.value) handleFlagSnapshot(s.snapshot_id, e.target.value); e.target.value = '' }}
                      >
                        <option value="" disabled>+ class</option>
                        <option value="pass">pass</option>
                        <option value="fail">fail</option>
                        <option value="null">null</option>
                      </select>
                  }
                </td>
                <td className="row-actions">
                  <button className="btn-edit" onClick={() => openEditModal(s)}>Edit</button>
                  <button className="btn-delete" onClick={() => handleDelete(s.snapshot_id)}>Delete</button>
                </td>
              </tr>
            ))}
            {snapshots.items.length === 0 && !snapshotsFetching && (
              <tr>
                <td colSpan={11} style={{ textAlign: 'center', padding: '20px', color: '#475569' }}>
                  No snapshots yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>

        {snapshots.total > PAGE_SIZE && (
          <div style={{ display: 'flex', gap: 8, padding: '12px 0', justifyContent: 'center' }}>
            <button
              className="btn-cancel"
              disabled={snapshotsPage === 0}
              onClick={() => fetchSnapshots(snapshotsPage - 1)}
            >
              ← Prev
            </button>
            <span className="snapshot-meta" style={{ lineHeight: '38px' }}>
              {snapshotsPage * PAGE_SIZE + 1}–{Math.min((snapshotsPage + 1) * PAGE_SIZE, snapshots.total)} of {snapshots.total}
            </span>
            <button
              className="btn-cancel"
              disabled={(snapshotsPage + 1) * PAGE_SIZE >= snapshots.total}
              onClick={() => fetchSnapshots(snapshotsPage + 1)}
            >
              Next →
            </button>
          </div>
        )}
      </div>

      {showEditModal && (
        <div className="modal-overlay" onClick={() => setShowEditModal(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h2>Edit Snapshot #{editingSnapshot?.snapshot_id}</h2>
            <form onSubmit={handleEditSubmit} className="order-form">
              <div style={{ marginBottom: 12 }}>
                <img
                  src={`${API_BASE}${editingSnapshot?.url}`}
                  alt="preview"
                  style={{ width: '100%', maxHeight: 180, objectFit: 'contain', borderRadius: 6, border: '1px solid #2d3148' }}
                />
              </div>
              <div className="form-row">
                <label>Result ID</label>
                <input value={editingSnapshot?.result_id ?? ''} readOnly style={{ opacity: 0.5 }} />
              </div>
              <div className="form-row">
                <label>Order ID</label>
                <input
                  name="order_id"
                  value={editForm.order_id}
                  onChange={e => setEditForm(prev => ({ ...prev, order_id: e.target.value }))}
                  placeholder="e.g. P000000001 (leave blank to unlink)"
                />
              </div>
              <div className="modal-actions">
                <button type="submit" disabled={editSubmitting}>
                  {editSubmitting ? 'Saving...' : 'Save'}
                </button>
                <button type="button" className="btn-cancel" onClick={() => setShowEditModal(false)}>Cancel</button>
              </div>
              {editStatus && <p className={`status-msg ${editStatus.type}`}>{editStatus.message}</p>}
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
