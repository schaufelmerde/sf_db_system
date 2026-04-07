import { useState } from 'react'
import { SHIP_TYPES } from '../constants.js'

const API_BASE = ''

export default function ShipsTab({ ships, onRefresh }) {
  const [showModal, setShowModal] = useState(false)
  const [editingShip, setEditingShip] = useState(null)
  const [form, setForm] = useState({
    ship_name: '',
    ship_type: '',
    status: 'BUILDING',
    start_date: '',
    target_date: '',
  })
  const [status, setStatus] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const openAdd = () => {
    setEditingShip(null)
    setForm({ ship_name: '', ship_type: '', status: 'BUILDING', start_date: '', target_date: '' })
    setStatus(null)
    setShowModal(true)
  }

  const openEdit = (s) => {
    setEditingShip(s)
    setForm({
      ship_name: s.ship_name ?? '',
      ship_type: s.ship_type ?? '',
      status: s.status ?? 'BUILDING',
      start_date: s.start_date ? s.start_date.split('T')[0] : '',
      target_date: s.target_date ? s.target_date.split('T')[0] : '',
    })
    setStatus(null)
    setShowModal(true)
  }

  const handleChange = e => {
    setForm(prev => ({ ...prev, [e.target.name]: e.target.value }))
  }

  const handleSubmit = async e => {
    e.preventDefault()
    setSubmitting(true)
    setStatus(null)
    try {
      const isEdit = editingShip !== null
      const res = await fetch(
        isEdit ? `${API_BASE}/api/ships/${editingShip.ship_id}` : `${API_BASE}/api/ships`,
        {
          method: isEdit ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(form),
        }
      )
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`)
      setStatus({ type: 'success', message: json.message })
      if (!isEdit) setForm({ ship_name: '', ship_type: '', status: 'BUILDING', start_date: '', target_date: '' })
      await onRefresh()
    } catch (err) {
      setStatus({ type: 'error', message: err.message })
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (ship_id) => {
    if (!window.confirm(`Delete ship ${ship_id}?`)) return
    try {
      const res = await fetch(`${API_BASE}/api/ships/${ship_id}`, { method: 'DELETE' })
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`)
      await onRefresh()
    } catch (err) {
      alert(err.message)
    }
  }

  return (
    <div className="panel tab-panel">
      <div className="panel-header">
        <h2>Ships ({ships.length})</h2>
        <button className="btn-register" onClick={openAdd}>+ Add Ship</button>
      </div>
      <ul>
        {ships.map(s => (
          <li key={s.ship_id}>
            <span className="id">{s.ship_id}</span>
            <span className="item-name">{s.ship_name}</span>
            <span className={`status-badge status-${s.status?.toLowerCase()}`}>{s.status}</span>
            <span className="ship-dates">
              {s.start_date ? s.start_date.split('T')[0] : '—'} → {s.target_date ? s.target_date.split('T')[0] : '—'}
            </span>
            <button className="btn-edit" onClick={() => openEdit(s)}>Edit</button>
            <button className="btn-delete" onClick={() => handleDelete(s.ship_id)}>Delete</button>
          </li>
        ))}
      </ul>

      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h2>{editingShip ? 'Edit Ship' : 'Add Ship'}</h2>
            <form onSubmit={handleSubmit} className="order-form">
              <div className="form-row">
                <label>Ship Name</label>
                <input
                  name="ship_name"
                  value={form.ship_name}
                  onChange={handleChange}
                  placeholder="e.g. MV Horizon"
                  required
                />
              </div>
              <div className="form-row">
                <label>Ship Type</label>
                <select name="ship_type" value={form.ship_type} onChange={handleChange}>
                  <option value="">-- select --</option>
                  {SHIP_TYPES.map(t => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              </div>
              <div className="form-row">
                <label>Status</label>
                <select name="status" value={form.status} onChange={handleChange}>
                  <option value="PLANNING">PLANNING</option>
                  <option value="BUILDING">BUILDING</option>
                  <option value="LAUNCHED">LAUNCHED</option>
                  <option value="COMPLETE">COMPLETE</option>
                </select>
              </div>
              <div className="form-row">
                <label>Start Date</label>
                <input type="date" name="start_date" value={form.start_date} onChange={handleChange} />
              </div>
              <div className="form-row">
                <label>Target Date</label>
                <input type="date" name="target_date" value={form.target_date} onChange={handleChange} />
              </div>
              <div className="modal-actions">
                <button type="submit" disabled={submitting}>
                  {submitting ? 'Saving...' : editingShip ? 'Save Changes' : 'Add Ship'}
                </button>
                <button type="button" className="btn-cancel" onClick={() => setShowModal(false)}>Cancel</button>
              </div>
              {status && <p className={`status-msg ${status.type}`}>{status.message}</p>}
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
