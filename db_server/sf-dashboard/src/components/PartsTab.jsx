import { useState } from 'react'

const API_BASE = ''

export default function PartsTab({ parts, onRefresh }) {
  const [showModal, setShowModal] = useState(false)
  const [editingPart, setEditingPart] = useState(null)
  const [form, setForm] = useState({
    part_name: '',
    part_category: '',
    unit_cost: '',
    unit_weight_kg: '',
    sort_bin: '',
    description: '',
  })
  const [status, setStatus] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const handleChange = e => {
    setForm(prev => ({ ...prev, [e.target.name]: e.target.value }))
  }

  const openAdd = () => {
    setEditingPart(null)
    setForm({ part_name: '', part_category: '', unit_cost: '', unit_weight_kg: '', sort_bin: '', description: '' })
    setStatus(null)
    setShowModal(true)
  }

  const openEdit = async (p) => {
    setEditingPart(p)
    setStatus(null)
    setShowModal(true)
    try {
      const res = await fetch(`${API_BASE}/api/parts/${p.part_id}`)
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
      setForm({
        part_name: data.part_name ?? '',
        part_category: data.part_category ?? '',
        unit_cost: data.unit_cost ?? '',
        unit_weight_kg: data.unit_weight_kg ?? '',
        sort_bin: data.sort_bin ?? '',
        description: data.description ?? '',
      })
    } catch (err) {
      setStatus({ type: 'error', message: err.message })
    }
  }

  const handleSubmit = async e => {
    e.preventDefault()
    setSubmitting(true)
    setStatus(null)
    try {
      const isEdit = editingPart !== null
      const res = await fetch(
        isEdit ? `${API_BASE}/api/parts/${editingPart.part_id}` : `${API_BASE}/api/parts`,
        {
          method: isEdit ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(form),
        }
      )
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`)
      setStatus({ type: 'success', message: isEdit ? json.message : `${json.message} — ID: ${json.part_id}` })
      if (!isEdit) setForm({ part_name: '', part_category: '', unit_cost: '', unit_weight_kg: '', sort_bin: '', description: '' })
      await onRefresh()
    } catch (err) {
      setStatus({ type: 'error', message: err.message })
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (part_id) => {
    if (!window.confirm(`Delete part ${part_id}?`)) return
    try {
      const res = await fetch(`${API_BASE}/api/parts/${part_id}`, { method: 'DELETE' })
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
        <h2>Parts ({parts.length})</h2>
        <button className="btn-register" onClick={openAdd}>+ Add Part</button>
      </div>
      <ul>
        {parts.map(p => (
          <li key={p.part_id}>
            <span className="id">{p.part_id}</span>
            <span className="item-name">{p.part_name}</span>
            <span className="item-meta">{p.part_category ?? ''}</span>
            <button className="btn-edit" onClick={() => openEdit(p)}>Edit</button>
            <button className="btn-delete" onClick={() => handleDelete(p.part_id)}>Delete</button>
          </li>
        ))}
      </ul>

      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h2>{editingPart ? 'Edit Part' : 'Add Part'}</h2>
            <form onSubmit={handleSubmit} className="order-form">
              <div className="form-row">
                <label>Part Name</label>
                <input
                  name="part_name"
                  value={form.part_name}
                  onChange={handleChange}
                  placeholder="e.g. Hull Block A"
                  required
                />
              </div>
              <div className="form-row">
                <label>Category</label>
                <input
                  name="part_category"
                  value={form.part_category}
                  onChange={handleChange}
                  placeholder="e.g. Hull Block, Pipe Spool, Bracket"
                />
              </div>
              <div className="form-row">
                <label>Unit Cost (KRW)</label>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  name="unit_cost"
                  value={form.unit_cost}
                  onChange={handleChange}
                  placeholder="e.g. 45000"
                />
              </div>
              <div className="form-row">
                <label>Weight (kg)</label>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  name="unit_weight_kg"
                  value={form.unit_weight_kg}
                  onChange={handleChange}
                  placeholder="e.g. 12.5"
                />
              </div>
              <div className="form-row">
                <label>Sort Bin</label>
                <select name="sort_bin" value={form.sort_bin} onChange={handleChange}>
                  <option value="">-- none --</option>
                  <option value="1">1</option>
                  <option value="2">2</option>
                  <option value="3">3</option>
                </select>
              </div>
              <div className="form-row">
                <label>Description</label>
                <input
                  name="description"
                  value={form.description}
                  onChange={handleChange}
                  placeholder="Optional notes"
                />
              </div>
              <div className="modal-actions">
                <button type="submit" disabled={submitting}>
                  {submitting ? 'Saving...' : editingPart ? 'Save Changes' : 'Add Part'}
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
