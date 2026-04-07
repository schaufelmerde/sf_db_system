import { useState } from 'react'

const API_BASE = ''

export default function CustomersTab({ customers, onRefresh }) {
  const [showModal, setShowModal] = useState(false)
  const [editingCustomer, setEditingCustomer] = useState(null)
  const [form, setForm] = useState({
    company_name: '',
    contact_name: '',
    phone: '',
    email: '',
  })
  const [status, setStatus] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const handleChange = e => {
    setForm(prev => ({ ...prev, [e.target.name]: e.target.value }))
  }

  const openAdd = () => {
    setEditingCustomer(null)
    setForm({ company_name: '', contact_name: '', phone: '', email: '' })
    setStatus(null)
    setShowModal(true)
  }

  const openEdit = (c) => {
    setEditingCustomer(c)
    setForm({
      customer_id: c.customer_id,
      company_name: c.company_name,
      contact_name: c.contact_name || '',
      phone: c.phone || '',
      email: c.email || '',
    })
    setStatus(null)
    setShowModal(true)
  }

  const handleSubmit = async e => {
    e.preventDefault()
    setSubmitting(true)
    setStatus(null)
    try {
      const isEdit = editingCustomer !== null
      const res = await fetch(
        isEdit ? `${API_BASE}/api/customers/${editingCustomer.customer_id}` : `${API_BASE}/api/customers`,
        {
          method: isEdit ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(form),
        }
      )
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`)
      setStatus({ type: 'success', message: json.message })
      if (!isEdit) setForm({ company_name: '', contact_name: '', phone: '', email: '' })
      await onRefresh()
    } catch (err) {
      setStatus({ type: 'error', message: err.message })
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (customer_id) => {
    if (!window.confirm(`Delete customer ${customer_id}?`)) return
    try {
      const res = await fetch(`${API_BASE}/api/customers/${customer_id}`, { method: 'DELETE' })
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
        <h2>Customers ({customers.length})</h2>
        <button className="btn-register" onClick={openAdd}>+ Register</button>
      </div>
      <ul>
        {customers.map(c => (
          <li key={c.customer_id}>
            <span className="id">{c.customer_id}</span>
            <span className="item-name">{c.company_name}</span>
            <span className="item-meta">{c.contact_name ?? ''}</span>
            <button className="btn-edit" onClick={() => openEdit(c)}>Edit</button>
            <button className="btn-delete" onClick={() => handleDelete(c.customer_id)}>Delete</button>
          </li>
        ))}
      </ul>

      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h2>{editingCustomer ? 'Edit Customer' : 'Register Customer'}</h2>
            <form onSubmit={handleSubmit} className="order-form">
              {editingCustomer && (
                <div className="form-row">
                  <label>Customer ID</label>
                  <input
                    name="customer_id"
                    value={form.customer_id || ''}
                    onChange={handleChange}
                    required
                  />
                </div>
              )}
              <div className="form-row">
                <label>Company Name</label>
                <input
                  name="company_name"
                  value={form.company_name}
                  onChange={handleChange}
                  placeholder="e.g. Acme Corp"
                  required
                />
              </div>
              <div className="form-row">
                <label>Contact Name</label>
                <input
                  name="contact_name"
                  value={form.contact_name}
                  onChange={handleChange}
                  placeholder="e.g. Jane Doe"
                  required
                />
              </div>
              <div className="form-row">
                <label>Phone</label>
                <input
                  name="phone"
                  value={form.phone}
                  onChange={handleChange}
                  placeholder="e.g. +1 555 0100"
                  required
                />
              </div>
              <div className="form-row">
                <label>Email</label>
                <input
                  type="email"
                  name="email"
                  value={form.email}
                  onChange={handleChange}
                  placeholder="e.g. jane@acme.com"
                  required
                />
              </div>
              <div className="modal-actions">
                <button type="submit" disabled={submitting}>
                  {submitting ? 'Saving...' : editingCustomer ? 'Save Changes' : 'Register'}
                </button>
                <button type="button" className="btn-cancel" onClick={() => setShowModal(false)}>
                  Cancel
                </button>
              </div>
              {status && (
                <p className={`status-msg ${status.type}`}>{status.message}</p>
              )}
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
