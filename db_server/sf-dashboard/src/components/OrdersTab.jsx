import { useState } from 'react'
import { SHIP_TYPES } from '../constants.js'

const API_BASE = ''

export default function OrdersTab({ orders, parts, customers, onRefreshOrders, onRefreshData }) {
  const [form, setForm] = useState({
    customer_id: '',
    ship_type: '',
    part1_id: '',
    part2_id: '',
    due_date: '',
  })
  const [submitStatus, setSubmitStatus] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const [showOrderModal, setShowOrderModal] = useState(false)
  const [editingOrder, setEditingOrder] = useState(null)
  const [orderForm, setOrderForm] = useState({
    status: '',
    priority: '',
    due_date: '',
    notes: '',
    part1_id: '',
    part2_id: '',
    item_id: '',
    ship_type: '',
  })
  const [orderStatus, setOrderStatus] = useState(null)
  const [orderSubmitting, setOrderSubmitting] = useState(false)

  const [expandedOrder, setExpandedOrder] = useState(null)
  const [snapshotHistory, setSnapshotHistory] = useState({})
  const [snapshotLoading, setSnapshotLoading] = useState(false)

  const handleChange = e => {
    setForm(prev => ({ ...prev, [e.target.name]: e.target.value }))
  }

  const handleSubmit = async e => {
    e.preventDefault()
    setSubmitting(true)
    setSubmitStatus(null)
    try {
      const res = await fetch(`${API_BASE}/api/orders`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          customer_id: form.customer_id,
          ship_type: form.ship_type || null,
          part1_id: form.part1_id,
          part2_id: form.part2_id,
          due_date: form.due_date || null,
        }),
      })
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`)
      setSubmitStatus({ type: 'success', message: json.message })
      setForm({ customer_id: '', ship_type: '', part1_id: '', part2_id: '', due_date: '' })
      await onRefreshOrders()
      await onRefreshData()
    } catch (err) {
      setSubmitStatus({ type: 'error', message: err.message })
    } finally {
      setSubmitting(false)
    }
  }

  const openEditOrderModal = (o) => {
    setEditingOrder(o)
    setOrderForm({
      status: o.status ?? '',
      priority: o.priority ?? '',
      due_date: o.due_date ? o.due_date.split('T')[0] : '',
      notes: o.notes ?? '',
      part1_id: o.part1_id ?? '',
      part2_id: o.part2_id ?? '',
      item_id: o.item_id ?? '',
      ship_type: o.ship_type ?? '',
    })
    setOrderStatus(null)
    setShowOrderModal(true)
  }

  const handleOrderChange = e => {
    setOrderForm(prev => ({ ...prev, [e.target.name]: e.target.value }))
  }

  const handleOrderSubmit = async e => {
    e.preventDefault()
    setOrderSubmitting(true)
    setOrderStatus(null)
    try {
      const res = await fetch(`${API_BASE}/api/orders/${editingOrder.order_id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(orderForm),
      })
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`)
      setOrderStatus({ type: 'success', message: json.message })
      await onRefreshOrders()
    } catch (err) {
      setOrderStatus({ type: 'error', message: err.message })
    } finally {
      setOrderSubmitting(false)
    }
  }

  const handleDeleteOrder = async (order_id) => {
    if (!window.confirm(`Delete order ${order_id}?`)) return
    try {
      const res = await fetch(`${API_BASE}/api/orders/${order_id}`, { method: 'DELETE' })
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || `HTTP ${res.status}`)
      await onRefreshOrders()
    } catch (err) {
      alert(err.message)
    }
  }

  const toggleSnapshotHistory = async (order_id) => {
    if (expandedOrder === order_id) {
      setExpandedOrder(null)
      return
    }
    setExpandedOrder(order_id)
    if (snapshotHistory[order_id]) return
    setSnapshotLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/orders/${order_id}/snapshots`)
      if (res.ok) {
        const json = await res.json()
        setSnapshotHistory(prev => ({ ...prev, [order_id]: json }))
      }
    } finally {
      setSnapshotLoading(false)
    }
  }

  const activeOrders = orders.filter(o => o.status !== 'COMPLETE')
  const completedOrders = orders.filter(o => o.status === 'COMPLETE')

  const OrderTable = ({ rows, showActions }) => (
    <table className="orders-table">
      <thead>
        <tr>
          <th></th>
          <th>Order ID</th>
          <th>Customer</th>
          <th>Ship Type</th>
          <th>Part 1</th>
          <th>Part 2</th>
          <th>Status</th>
          <th>Priority</th>
          <th>Due Date</th>
          {showActions && <th></th>}
        </tr>
      </thead>
      <tbody>
        {rows.map(o => {
          const isExpanded = expandedOrder === o.order_id
          const cycles = snapshotHistory[o.order_id] || []
          return (
            <>
              <tr key={o.order_id}>
                <td>
                  <button className="btn-expand" onClick={() => toggleSnapshotHistory(o.order_id)}>
                    {isExpanded ? '▾' : '▸'}
                  </button>
                </td>
                <td><span className="id">{o.order_id}</span></td>
                <td>{o.company_name ?? o.customer_id}</td>
                <td>{o.ship_type ?? '—'}</td>
                <td>{o.part1_id ?? '—'}</td>
                <td>{o.part2_id ?? '—'}</td>
                <td><span className={`status-badge status-${o.status?.toLowerCase()}`}>{o.status}</span></td>
                <td>{o.priority ?? '—'}</td>
                <td>{o.due_date ? o.due_date.split('T')[0] : '—'}</td>
                {showActions && (
                  <td className="row-actions">
                    <button className="btn-edit" onClick={() => openEditOrderModal(o)}>Edit</button>
                    <button className="btn-delete" onClick={() => handleDeleteOrder(o.order_id)}>Delete</button>
                  </td>
                )}
              </tr>
              {isExpanded && (
                <tr key={`${o.order_id}-history`} className="snapshot-history-row">
                  <td colSpan={showActions ? 10 : 9}>
                    {snapshotLoading && !cycles.length
                      ? <p className="snapshot-loading">Loading inspection history...</p>
                      : cycles.length === 0
                        ? <p className="snapshot-empty">No inspection records for this order.</p>
                        : <div className="snapshot-cycles">
                            {cycles.map((cycle, i) => (
                              <div key={cycle.result_id} className="snapshot-cycle">
                                <div className="snapshot-cycle-header">
                                  <span className="snapshot-cycle-num">Cycle {i + 1}</span>
                                  <span className={`status-badge status-${cycle.result_status?.toLowerCase()}`}>{cycle.result_status}</span>
                                  {cycle.detected_class && <span className="snapshot-meta">{cycle.detected_class}</span>}
                                  {cycle.confidence != null && <span className="snapshot-meta">{cycle.confidence.toFixed(1)}%</span>}
                                  {cycle.inspected_at && <span className="snapshot-meta">{cycle.inspected_at.split('.')[0]}</span>}
                                </div>
                                {cycle.snapshots.length > 0
                                  ? <div className="snapshot-images">
                                      {cycle.snapshots.map(s => (
                                        <div key={s.snapshot_id} className="snapshot-item">
                                          <img src={`${API_BASE}${s.url}`} alt={s.snapshot_type} />
                                          <span className="snapshot-type-label">{s.snapshot_type}</span>
                                        </div>
                                      ))}
                                    </div>
                                  : <p className="snapshot-empty">No images for this cycle.</p>
                                }
                              </div>
                            ))}
                          </div>
                    }
                  </td>
                </tr>
              )}
            </>
          )
        })}
      </tbody>
    </table>
  )

  return (
    <div className="main-content">
      <div className="panel order-form-panel">
        <h2>Create Order</h2>
        <form onSubmit={handleSubmit}>
          <div className="order-form-grid">
            <div className="form-row">
              <label>Customer</label>
              <select name="customer_id" value={form.customer_id} onChange={handleChange} required>
                <option value="">-- select --</option>
                {customers.map(c => (
                  <option key={c.customer_id} value={c.customer_id}>{c.company_name}</option>
                ))}
              </select>
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
              <label>Due Date</label>
              <input type="date" name="due_date" value={form.due_date} onChange={handleChange} />
            </div>
            <div className="form-row">
              <label>Part 1</label>
              <select name="part1_id" value={form.part1_id} onChange={handleChange} required>
                <option value="">-- select --</option>
                {parts.map(p => (
                  <option key={p.part_id} value={p.part_id}>{p.part_name}</option>
                ))}
              </select>
            </div>
            <div className="form-row">
              <label>Part 2</label>
              <select name="part2_id" value={form.part2_id} onChange={handleChange} required>
                <option value="">-- select --</option>
                {parts.map(p => (
                  <option key={p.part_id} value={p.part_id}>{p.part_name}</option>
                ))}
              </select>
            </div>
            <div className="form-submit-row">
              <button type="submit" disabled={submitting}>
                {submitting ? 'Submitting...' : 'Submit Order'}
              </button>
              {submitStatus && (
                <p className={`status-msg ${submitStatus.type}`}>{submitStatus.message}</p>
              )}
            </div>
          </div>
        </form>
      </div>

      <div className="panel orders-panel">
        <h2>Active Orders ({activeOrders.length})</h2>
        {activeOrders.length === 0
          ? <p className="status-msg">No active orders.</p>
          : <OrderTable rows={activeOrders} showActions={true} />}
      </div>

      <div className="panel orders-panel">
        <h2>Completed Orders ({completedOrders.length})</h2>
        {completedOrders.length === 0
          ? <p className="status-msg">No completed orders.</p>
          : <OrderTable rows={completedOrders} showActions={true} />}
      </div>

      {showOrderModal && (
        <div className="modal-overlay" onClick={() => setShowOrderModal(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h2>Edit Order — {editingOrder?.order_id}</h2>
            <form onSubmit={handleOrderSubmit} className="order-form">
              <div className="form-row">
                <label>Status</label>
                <select name="status" value={orderForm.status} onChange={handleOrderChange} required>
                  <option value="PENDING">PENDING</option>
                  <option value="QUEUED">QUEUED</option>
                  <option value="IN_PROGRESS">IN_PROGRESS</option>
                  <option value="COMPLETE">COMPLETE</option>
                  <option value="CANCELLED">CANCELLED</option>
                  <option value="ON_HOLD">ON_HOLD</option>
                </select>
              </div>
              <div className="form-row">
                <label>Ship Type</label>
                <select name="ship_type" value={orderForm.ship_type} onChange={handleOrderChange}>
                  <option value="">-- none --</option>
                  {SHIP_TYPES.map(t => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              </div>
              <div className="form-row">
                <label>Priority</label>
                <input
                  type="number"
                  min="1"
                  max="5"
                  name="priority"
                  value={orderForm.priority}
                  onChange={handleOrderChange}
                  placeholder="1–5"
                />
              </div>
              <div className="form-row">
                <label>Due Date</label>
                <input type="date" name="due_date" value={orderForm.due_date} onChange={handleOrderChange} />
              </div>
              <div className="form-row">
                <label>Part 1</label>
                <select name="part1_id" value={orderForm.part1_id} onChange={handleOrderChange} required>
                  <option value="">-- select --</option>
                  {parts.map(p => (
                    <option key={p.part_id} value={p.part_id}>{p.part_name}</option>
                  ))}
                </select>
              </div>
              <div className="form-row">
                <label>Part 2</label>
                <select name="part2_id" value={orderForm.part2_id} onChange={handleOrderChange} required>
                  <option value="">-- select --</option>
                  {parts.map(p => (
                    <option key={p.part_id} value={p.part_id}>{p.part_name}</option>
                  ))}
                </select>
              </div>
              <div className="form-row">
                <label>Notes</label>
                <input
                  name="notes"
                  value={orderForm.notes}
                  onChange={handleOrderChange}
                  placeholder="Optional notes"
                />
              </div>
              <div className="modal-actions">
                <button type="submit" disabled={orderSubmitting}>
                  {orderSubmitting ? 'Saving...' : 'Save Changes'}
                </button>
                <button type="button" className="btn-cancel" onClick={() => setShowOrderModal(false)}>Cancel</button>
              </div>
              {orderStatus && <p className={`status-msg ${orderStatus.type}`}>{orderStatus.message}</p>}
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
