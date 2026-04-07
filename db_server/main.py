from fastapi import FastAPI, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect, Response
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import mysql.connector
from pydantic import BaseModel
import shutil, uuid, os, asyncio, json, subprocess, threading

SNAPSHOTS_DIR = os.path.join(os.path.dirname(__file__), "snapshots")
os.makedirs(SNAPSHOTS_DIR, exist_ok=True)

DATASET_DIR = r"D:\akim\cam_server\image_dataset"
DATASET_CLASSES = ("pass", "fail", "null")

TRAIN_SCRIPT = r"D:\akim\cam_server\train.py"
TRAIN_PYTHON = r"D:\akim\cam_server\venv\Scripts\python.exe"

# ── Training state ────────────────────────────────────────────────────────────
_train_log:  list[str] = []
_train_running:   bool = False
_train_exit_code: int | None = None

app = FastAPI()
app.mount("/snapshots", StaticFiles(directory=SNAPSHOTS_DIR), name="snapshots")
for _cls in DATASET_CLASSES:
    os.makedirs(os.path.join(DATASET_DIR, _cls), exist_ok=True)

# ── WebSocket broadcaster ─────────────────────────────────────────────────────

class OrderBroadcaster:
    def __init__(self):
        self._clients: list[WebSocket] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._clients.append(ws)

    def disconnect(self, ws: WebSocket):
        self._clients.remove(ws)

    async def _send(self, event: dict):
        dead = []
        for ws in self._clients:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.remove(ws)

    def broadcast(self, event: dict):
        """Thread-safe broadcast from sync route handlers."""
        if self._loop and self._clients:
            asyncio.run_coroutine_threadsafe(self._send(event), self._loop)

broadcaster = OrderBroadcaster()

@app.on_event("startup")
async def _store_loop():
    broadcaster.set_loop(asyncio.get_event_loop())

@app.websocket("/ws/orders")
async def ws_orders(ws: WebSocket):
    await broadcaster.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keep-alive ping/pong
    except WebSocketDisconnect:
        broadcaster.disconnect(ws)

# Enable CORS for React
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database Configuration
DB_CONFIGS = {
    "order": "sf_order",
    "inventory": "sf_inventory",
    "production": "sf_production",
    "report": "sf_report"
}

def get_db(db_key: str):
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="1234",
        database=DB_CONFIGS[db_key]
    )

# --- MIGRATIONS ---

@app.on_event("startup")
def run_migrations():
    conn = get_db("order")
    cursor = conn.cursor()
    prod_conn = get_db("production")
    prod_cur = prod_conn.cursor()
    for ddl in [
        # Remove old single-snapshot column (ignore if already gone)
        "ALTER TABLE sort_results DROP COLUMN snapshot_path",
        # Create dedicated snapshots table
        """CREATE TABLE IF NOT EXISTS inspection_snapshots (
            snapshot_id   INT          NOT NULL AUTO_INCREMENT,
            result_id     INT          NOT NULL,
            filename      VARCHAR(255) NOT NULL,
            snapshot_type ENUM('INITIAL','RECHECK','DEFECT_DETAIL','PASS') DEFAULT 'INITIAL',
            taken_at      DATETIME(3)  DEFAULT CURRENT_TIMESTAMP(3),
            notes         VARCHAR(200),
            dataset_label VARCHAR(10)  DEFAULT NULL,
            PRIMARY KEY (snapshot_id),
            INDEX idx_result (result_id)
        )""",
        "ALTER TABLE inspection_snapshots ADD COLUMN dataset_label VARCHAR(10) DEFAULT NULL",
    ]:
        try:
            prod_cur.execute(ddl)
            prod_conn.commit()
        except Exception:
            pass
    prod_conn.close()

    for ddl in [
        "ALTER TABLE orders ADD COLUMN ship_id VARCHAR(20) NULL",
        "ALTER TABLE orders ADD COLUMN ship_type VARCHAR(50) NULL",
    ]:
        try:
            cursor.execute(ddl)
            conn.commit()
        except Exception:
            pass  # column already exists
    conn.close()

    inv_conn = get_db("inventory")
    inv_cur = inv_conn.cursor()
    for ddl in [
        # Expand ship status ENUM to include FINISHED, change default to PLANNING
        "ALTER TABLE ships MODIFY COLUMN status ENUM('PLANNING','BUILDING','LAUNCHED','COMPLETE','FINISHED') DEFAULT 'PLANNING'",
    ]:
        try:
            inv_cur.execute(ddl)
            inv_conn.commit()
        except Exception:
            pass
    inv_conn.close()

# --- API ENDPOINTS ---

@app.get("/api/init-data")
def get_initial_data():
    """Fetches data from TWO different DBs for the React UI"""
    try:
        # 1. Get Ships and Parts from sf_inventory
        inv_conn = get_db("inventory")
        cursor = inv_conn.cursor(dictionary=True)
        
        cursor.execute("SELECT ship_id, ship_name, ship_type, status, start_date, target_date FROM ships")
        ships = cursor.fetchall()
        
        cursor.execute("SELECT part_id, part_name, part_category, unit_cost, unit_weight_kg, sort_bin, description FROM parts")
        parts = cursor.fetchall()
        
        inv_conn.close()

        # 2. Get Recent Customers from sf_order
        order_conn = get_db("order")
        cursor = order_conn.cursor(dictionary=True)
        cursor.execute("SELECT customer_id, company_name, contact_name, phone, email FROM customers")
        customers = cursor.fetchall()
        order_conn.close()

        return {"ships": ships, "parts": parts, "customers": customers}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ships")
def create_ship(data: dict):
    conn = get_db("inventory")
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COALESCE(MAX(CAST(SUBSTRING(ship_id, 6) AS UNSIGNED)), 0) + 1 FROM ships")
        next_num = cursor.fetchone()[0]
        ship_id = 'SHIP-' + str(next_num).zfill(3)

        sql = """
            INSERT INTO ships (ship_id, ship_name, ship_type, status, start_date, target_date)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        cursor.execute(sql, (
            ship_id,
            data['ship_name'],
            data.get('ship_type') or None,
            data.get('status') or 'BUILDING',
            data.get('start_date') or None,
            data.get('target_date') or None,
        ))
        conn.commit()
        return {"message": "Ship registered successfully", "ship_id": ship_id}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@app.put("/api/ships/{ship_id}")
def update_ship(ship_id: str, data: dict):
    conn = get_db("inventory")
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM ships WHERE ship_id=%s", (ship_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Ship not found")
        cursor.execute("""
            UPDATE ships
            SET ship_name=%s, ship_type=%s, status=%s, start_date=%s, target_date=%s
            WHERE ship_id=%s
        """, (
            data['ship_name'],
            data.get('ship_type') or None,
            data.get('status') or 'BUILDING',
            data.get('start_date') or None,
            data.get('target_date') or None,
            ship_id,
        ))
        conn.commit()
        return {"message": "Ship updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@app.post("/api/ships/batch-delete")
def batch_delete_ships(data: dict):
    ship_ids = data.get("ship_ids", [])
    if not ship_ids:
        raise HTTPException(status_code=400, detail="No ship IDs provided")

    ph = ",".join(["%s"] * len(ship_ids))

    inv_conn = get_db("inventory")
    inv_cur = inv_conn.cursor()
    try:
        inv_cur.execute(f"DELETE FROM ships WHERE ship_id IN ({ph})", ship_ids)
        deleted = inv_cur.rowcount
        inv_conn.commit()
    except Exception as e:
        inv_conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        inv_conn.close()

    order_conn = get_db("order")
    order_cur = order_conn.cursor()
    try:
        order_cur.execute(f"SELECT order_id FROM orders WHERE ship_id IN ({ph})", ship_ids)
        order_ids = [r[0] for r in order_cur.fetchall()]
        if order_ids:
            oph = ",".join(["%s"] * len(order_ids))
            order_cur.execute(f"DELETE FROM order_items WHERE order_id IN ({oph})", order_ids)
            order_cur.execute(f"DELETE FROM orders WHERE ship_id IN ({ph})", ship_ids)
            order_conn.commit()
            for oid in order_ids:
                broadcaster.broadcast({"event": "order_deleted", "order_id": oid})
    except Exception as e:
        order_conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        order_conn.close()

    return {"message": f"Deleted {deleted} ship(s)"}

@app.delete("/api/ships/{ship_id}")
def delete_ship(ship_id: str):
    inv_conn = get_db("inventory")
    inv_cur = inv_conn.cursor()
    try:
        inv_cur.execute("DELETE FROM ships WHERE ship_id=%s", (ship_id,))
        if inv_cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Ship not found")
        inv_conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        inv_conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        inv_conn.close()

    order_conn = get_db("order")
    order_cur = order_conn.cursor()
    try:
        order_cur.execute("SELECT order_id FROM orders WHERE ship_id=%s", (ship_id,))
        order_ids = [r[0] for r in order_cur.fetchall()]
        if order_ids:
            ph = ",".join(["%s"] * len(order_ids))
            order_cur.execute(f"DELETE FROM order_items WHERE order_id IN ({ph})", order_ids)
            order_cur.execute(f"DELETE FROM orders WHERE ship_id=%s", (ship_id,))
            order_conn.commit()
            for oid in order_ids:
                broadcaster.broadcast({"event": "order_deleted", "order_id": oid})
    except Exception as e:
        order_conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        order_conn.close()

    return {"message": "Ship deleted successfully"}

@app.post("/api/customers")
def create_customer(data: dict):
    """Registers a new customer into the sf_order database"""
    conn = get_db("order")
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COALESCE(MAX(customer_id), 0) + 1 FROM customers")
        next_id = str(int(cursor.fetchone()[0])).zfill(8)

        sql = """
            INSERT INTO customers (customer_id, company_name, contact_name, phone, email)
            VALUES (%s, %s, %s, %s, %s)
        """
        cursor.execute(sql, (
            next_id,
            data['company_name'],
            data['contact_name'],
            data['phone'],
            data['email'],
        ))
        conn.commit()
        return {"message": "Customer registered successfully"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@app.post("/api/parts")
def create_part(data: dict):
    """Registers a new part into sf_inventory"""
    conn = get_db("inventory")
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COALESCE(MAX(CAST(SUBSTRING(part_id, 6) AS UNSIGNED)), 0) + 1 FROM parts")
        next_num = cursor.fetchone()[0]
        part_id = 'PART-' + str(next_num).zfill(3)

        sql = """
            INSERT INTO parts (part_id, part_name, part_category, unit_cost, unit_weight_kg, sort_bin, description)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(sql, (
            part_id,
            data['part_name'],
            data.get('part_category') or None,
            data.get('unit_cost') or 0.00,
            data.get('unit_weight_kg') or None,
            data.get('sort_bin') or None,
            data.get('description') or None,
        ))
        conn.commit()
        return {"message": "Part registered successfully", "part_id": part_id}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@app.put("/api/customers/{customer_id}")
def update_customer(customer_id: str, data: dict):
    """Updates an existing customer's details"""
    conn = get_db("order")
    cursor = conn.cursor()
    try:
        new_id = data.get('customer_id', customer_id)
        if new_id != customer_id:
            cursor.execute("UPDATE orders SET customer_id=%s WHERE customer_id=%s", (new_id, customer_id))
        sql = """
            UPDATE customers
            SET customer_id=%s, company_name=%s, contact_name=%s, phone=%s, email=%s
            WHERE customer_id=%s
        """
        cursor.execute(sql, (
            new_id,
            data['company_name'],
            data['contact_name'],
            data['phone'],
            data['email'],
            customer_id,
        ))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Customer not found")
        conn.commit()
        return {"message": "Customer updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@app.get("/api/parts/{part_id}")
def get_part(part_id: str):
    conn = get_db("inventory")
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT part_id, part_name, part_category, unit_cost, unit_weight_kg, sort_bin, description FROM parts WHERE part_id=%s",
            (part_id,)
        )
        part = cursor.fetchone()
        if not part:
            raise HTTPException(status_code=404, detail="Part not found")
        return part
    finally:
        conn.close()

@app.put("/api/parts/{part_id}")
def update_part(part_id: str, data: dict):
    """Updates an existing part's details"""
    conn = get_db("inventory")
    cursor = conn.cursor()
    try:
        sql = """
            UPDATE parts
            SET part_name=%s, part_category=%s, unit_cost=%s, unit_weight_kg=%s, sort_bin=%s, description=%s
            WHERE part_id=%s
        """
        cursor.execute(sql, (
            data['part_name'],
            data.get('part_category') or None,
            data.get('unit_cost') or 0.00,
            data.get('unit_weight_kg') or None,
            data.get('sort_bin') or None,
            data.get('description') or None,
            part_id,
        ))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Part not found")
        conn.commit()
        return {"message": "Part updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@app.delete("/api/customers/{customer_id}")
def delete_customer(customer_id: str):
    conn = get_db("order")
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM customers WHERE customer_id=%s", (customer_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Customer not found")

        cursor.execute("SELECT order_id, ship_id FROM orders WHERE customer_id=%s", (customer_id,))
        rows = cursor.fetchall()
        order_ids = [r[0] for r in rows]
        ship_ids  = [r[1] for r in rows if r[1]]

        if order_ids:
            ph = ",".join(["%s"] * len(order_ids))
            cursor.execute(f"DELETE FROM order_items WHERE order_id IN ({ph})", order_ids)
            cursor.execute(f"DELETE FROM orders WHERE customer_id=%s", (customer_id,))

        cursor.execute("DELETE FROM customers WHERE customer_id=%s", (customer_id,))
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

    if ship_ids:
        inv_conn = get_db("inventory")
        inv_cur = inv_conn.cursor()
        try:
            ph = ",".join(["%s"] * len(ship_ids))
            inv_cur.execute(f"DELETE FROM ships WHERE ship_id IN ({ph})", ship_ids)
            inv_conn.commit()
        finally:
            inv_conn.close()

    for oid in order_ids:
        broadcaster.broadcast({"event": "order_deleted", "order_id": oid})

    return {"message": "Customer deleted successfully"}

@app.delete("/api/parts/{part_id}")
def delete_part(part_id: str):
    conn = get_db("inventory")
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM parts WHERE part_id=%s", (part_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Part not found")
        conn.commit()
        return {"message": "Part deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@app.get("/orders-display", response_class=FileResponse)
def orders_display():
    return FileResponse(os.path.join(os.path.dirname(__file__), "orders_display.html"))

@app.get("/api/orders")
def get_orders():
    conn = get_db("order")
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT o.order_id, o.customer_id, c.company_name,
                   o.status, o.priority, o.due_date, o.notes, o.order_date,
                   o.ship_id, o.ship_type,
                   oi.item_id, oi.part1_id, oi.part2_id, oi.item_status
            FROM orders o
            LEFT JOIN customers c ON o.customer_id = c.customer_id
            LEFT JOIN order_items oi ON o.order_id = oi.order_id
            ORDER BY o.order_date DESC
        """)
        return cursor.fetchall()
    finally:
        conn.close()

@app.get("/api/orders/{order_id}/snapshots")
def get_order_snapshots(order_id: str):
    """Returns all inspection snapshots for an order, grouped by sort result cycle."""
    conn = get_db("production")
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT
                sr.result_id, sr.status AS result_status, sr.created_at AS inspected_at,
                sr.detected_class, sr.confidence, sr.cycle_time_sec,
                s.snapshot_id, s.filename, s.snapshot_type, s.taken_at, s.notes
            FROM sort_results sr
            LEFT JOIN inspection_snapshots s ON sr.result_id = s.result_id
            WHERE sr.order_id = %s
            ORDER BY sr.created_at ASC, s.taken_at ASC
        """, (order_id,))
        rows = cursor.fetchall()

        # Group snapshots under their result cycle
        cycles = {}
        for r in rows:
            rid = r['result_id']
            if rid not in cycles:
                cycles[rid] = {
                    'result_id':     rid,
                    'result_status': r['result_status'],
                    'inspected_at':  str(r['inspected_at']) if r['inspected_at'] else None,
                    'detected_class': r['detected_class'],
                    'confidence':    float(r['confidence']) if r['confidence'] else None,
                    'cycle_time_sec': float(r['cycle_time_sec']) if r['cycle_time_sec'] else None,
                    'snapshots':     [],
                }
            if r['snapshot_id']:
                cycles[rid]['snapshots'].append({
                    'snapshot_id':   r['snapshot_id'],
                    'filename':      r['filename'],
                    'url':           f"/snapshots/{r['filename']}",
                    'snapshot_type': r['snapshot_type'],
                    'taken_at':      str(r['taken_at']) if r['taken_at'] else None,
                    'notes':         r['notes'],
                })
        return list(cycles.values())
    finally:
        conn.close()

_ORDER_TO_SHIP_STATUS = {
    'IN_PROGRESS': 'BUILDING',
    'COMPLETE':    'FINISHED',
    'PENDING':     'PLANNING',
    'QUEUED':      'PLANNING',
    'ON_HOLD':     'PLANNING',
    'CANCELLED':   'PLANNING',
}

@app.put("/api/orders/{order_id}")
def update_order(order_id: str, data: dict):
    conn = get_db("order")
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT ship_id FROM orders WHERE order_id=%s", (order_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found")
        ship_id = row[0]

        cursor.execute("""
            UPDATE orders
            SET status=%s, priority=%s, due_date=%s, notes=%s, ship_type=%s
            WHERE order_id=%s
        """, (
            data.get('status'),
            data.get('priority') or None,
            data.get('due_date') or None,
            data.get('notes') or None,
            data.get('ship_type') or None,
            order_id,
        ))
        if data.get('item_id'):
            cursor.execute("""
                UPDATE order_items
                SET part1_id=%s, part2_id=%s
                WHERE item_id=%s
            """, (data['part1_id'], data['part2_id'], data['item_id']))
        conn.commit()

        # Sync ship status in sf_inventory
        new_status = data.get('status')
        ship_status = _ORDER_TO_SHIP_STATUS.get(new_status)
        if ship_id and ship_status:
            inv_conn = get_db("inventory")
            inv_cur = inv_conn.cursor()
            try:
                inv_cur.execute("UPDATE ships SET status=%s WHERE ship_id=%s", (ship_status, ship_id))
                inv_conn.commit()
            finally:
                inv_conn.close()

        broadcaster.broadcast({"event": "order_updated", "order_id": order_id, "status": new_status})
        return {"message": "Order updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@app.delete("/api/orders/{order_id}")
def delete_order(order_id: str):
    conn = get_db("order")
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT ship_id FROM orders WHERE order_id=%s", (order_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found")
        ship_id = row[0]

        cursor.execute("DELETE FROM order_items WHERE order_id=%s", (order_id,))
        cursor.execute("DELETE FROM orders WHERE order_id=%s", (order_id,))
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

    if ship_id:
        inv_conn = get_db("inventory")
        inv_cur = inv_conn.cursor()
        try:
            inv_cur.execute("DELETE FROM ships WHERE ship_id=%s", (ship_id,))
            inv_conn.commit()
        finally:
            inv_conn.close()

    broadcaster.broadcast({"event": "order_deleted", "order_id": order_id})
    return {"message": "Order deleted successfully"}

@app.post("/api/orders")
def create_order(data: dict):
    """Saves a new order and auto-creates a ship in sf_inventory"""
    from datetime import date
    order_conn = get_db("order")
    inv_conn = get_db("inventory")
    order_cur = order_conn.cursor()
    inv_cur = inv_conn.cursor()
    try:
        # Generate order ID
        order_cur.execute("SELECT COALESCE(MAX(CAST(SUBSTRING(order_id, 2) AS UNSIGNED)), 0) + 1 FROM orders")
        order_id = 'P' + str(order_cur.fetchone()[0]).zfill(9)

        # Auto-create ship in sf_inventory
        ship_id = None
        ship_type = data.get('ship_type') or None
        if ship_type:
            inv_cur.execute("SELECT COALESCE(MAX(CAST(SUBSTRING(ship_id, 6) AS UNSIGNED)), 0) + 1 FROM ships")
            next_ship_num = inv_cur.fetchone()[0]
            ship_id = 'SHIP-' + str(next_ship_num).zfill(3)
            ship_name = f"{ship_type} {str(next_ship_num).zfill(3)}"
            inv_cur.execute(
                "INSERT INTO ships (ship_id, ship_name, ship_type, status, start_date, target_date) VALUES (%s, %s, %s, 'PLANNING', %s, %s)",
                (ship_id, ship_name, ship_type, date.today(), data.get('due_date') or None)
            )
            inv_conn.commit()

        # Insert order
        order_cur.execute(
            "INSERT INTO orders (order_id, customer_id, status, due_date, ship_type, ship_id) VALUES (%s, %s, 'PENDING', %s, %s, %s)",
            (order_id, data['customer_id'], data.get('due_date') or None, ship_type, ship_id)
        )

        # Insert order items
        order_cur.execute(
            "INSERT INTO order_items (order_id, part1_id, part2_id) VALUES (%s, %s, %s)",
            (order_id, data['part1_id'], data['part2_id'])
        )

        order_conn.commit()
        broadcaster.broadcast({"event": "order_created", "order_id": order_id})
        return {"message": "Order created successfully", "order_id": order_id, "ship_id": ship_id}
    except Exception as e:
        order_conn.rollback()
        inv_conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        order_conn.close()
        inv_conn.close()

@app.post("/api/orders/generate")
def generate_random_orders(data: dict):
    """Generate random orders using existing customers and parts."""
    import random
    from datetime import date, timedelta

    count = max(1, min(int(data.get('count', 1)), 100))

    SHIP_TYPES = [
        'Bulk Carrier', 'Container Ship', 'Tanker', 'LNG Carrier',
        'Naval Vessel', 'Offshore Platform', 'Ferry', 'Other',
    ]

    order_conn = get_db("order")
    inv_conn = get_db("inventory")
    order_cur = order_conn.cursor()
    inv_cur = inv_conn.cursor()
    try:
        order_cur.execute("SELECT customer_id FROM customers")
        customers = [r[0] for r in order_cur.fetchall()]
        if not customers:
            raise HTTPException(status_code=400, detail="No customers in database")

        inv_cur.execute("SELECT part_id FROM parts")
        parts = [r[0] for r in inv_cur.fetchall()]
        if len(parts) < 2:
            raise HTTPException(status_code=400, detail="Need at least 2 parts in database")

        created = []
        for _ in range(count):
            order_cur.execute("SELECT COALESCE(MAX(CAST(SUBSTRING(order_id, 2) AS UNSIGNED)), 0) + 1 FROM orders")
            order_id = 'P' + str(order_cur.fetchone()[0]).zfill(9)

            customer_id = random.choice(customers)
            ship_type = random.choice(SHIP_TYPES)
            p1, p2 = random.sample(parts, 2)
            due_days = random.randint(30, 180)
            due_date = (date.today() + timedelta(days=due_days)).isoformat()

            inv_cur.execute("SELECT COALESCE(MAX(CAST(SUBSTRING(ship_id, 6) AS UNSIGNED)), 0) + 1 FROM ships")
            next_ship_num = inv_cur.fetchone()[0]
            ship_id = 'SHIP-' + str(next_ship_num).zfill(3)
            ship_name = f"{ship_type} {str(next_ship_num).zfill(3)}"
            inv_cur.execute(
                "INSERT INTO ships (ship_id, ship_name, ship_type, status, start_date, target_date) VALUES (%s, %s, %s, 'PLANNING', %s, %s)",
                (ship_id, ship_name, ship_type, date.today(), due_date)
            )
            inv_conn.commit()

            order_cur.execute(
                "INSERT INTO orders (order_id, customer_id, status, due_date, ship_type, ship_id) VALUES (%s, %s, 'PENDING', %s, %s, %s)",
                (order_id, customer_id, due_date, ship_type, ship_id)
            )
            order_cur.execute(
                "INSERT INTO order_items (order_id, part1_id, part2_id) VALUES (%s, %s, %s)",
                (order_id, p1, p2)
            )
            order_conn.commit()
            broadcaster.broadcast({"event": "order_created", "order_id": order_id})
            created.append(order_id)

        return {"message": f"Generated {len(created)} order(s)", "order_ids": created}
    except HTTPException:
        raise
    except Exception as e:
        order_conn.rollback()
        inv_conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        order_conn.close()
        inv_conn.close()

@app.post("/api/sort-results/{result_id}/snapshot")
async def upload_snapshot(
    result_id: int,
    file: UploadFile = File(...),
    snapshot_type: str = "INITIAL",
    notes: str = "",
):
    conn = get_db("production")
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM sort_results WHERE result_id=%s", (result_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Result not found")

        ext = os.path.splitext(file.filename)[1] or ".jpg"
        filename = f"{result_id}_{uuid.uuid4().hex[:8]}{ext}"
        dest = os.path.join(SNAPSHOTS_DIR, filename)
        with open(dest, "wb") as f:
            shutil.copyfileobj(file.file, f)

        cursor.execute(
            """INSERT INTO inspection_snapshots (result_id, filename, snapshot_type, notes)
               VALUES (%s, %s, %s, %s)""",
            (result_id, filename, snapshot_type, notes or None)
        )
        conn.commit()
        snapshot_id = cursor.lastrowid
        return {"snapshot_id": snapshot_id, "filename": filename, "url": f"/snapshots/{filename}"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@app.get("/api/sort-results/{result_id}/snapshots")
def get_snapshots(result_id: int):
    conn = get_db("production")
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT snapshot_id, filename, snapshot_type, taken_at, notes
               FROM inspection_snapshots WHERE result_id=%s ORDER BY taken_at""",
            (result_id,)
        )
        rows = cursor.fetchall()
        for r in rows:
            r["url"] = f"/snapshots/{r['filename']}"
        return rows
    finally:
        conn.close()

@app.get("/api/snapshots")
def list_all_snapshots(limit: int = 200, offset: int = 0):
    """All snapshots with associated sort_result metadata."""
    conn = get_db("production")
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT
                s.snapshot_id, s.result_id, s.filename, s.snapshot_type,
                s.taken_at, s.notes, s.dataset_label,
                sr.order_id, sr.status AS result_status,
                sr.detected_class, sr.confidence
            FROM inspection_snapshots s
            LEFT JOIN sort_results sr ON s.result_id = sr.result_id
            ORDER BY s.taken_at DESC
            LIMIT %s OFFSET %s
        """, (limit, offset))
        rows = cursor.fetchall()
        for r in rows:
            r["url"] = f"/snapshots/{r['filename']}"
            if r["taken_at"]:
                r["taken_at"] = str(r["taken_at"])
            if r["confidence"] is not None:
                r["confidence"] = float(r["confidence"])
        cursor.execute("SELECT COUNT(*) AS total FROM inspection_snapshots")
        total = cursor.fetchone()["total"]
        return {"total": total, "items": rows}
    finally:
        conn.close()

@app.patch("/api/sort-results/{result_id}")
def patch_sort_result(result_id: int, body: dict):
    """Update fields on a sort_result row (currently order_id)."""
    allowed = {"order_id"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    conn = get_db("production")
    cursor = conn.cursor()
    try:
        set_clause = ", ".join(f"{k}=%s" for k in updates)
        cursor.execute(
            f"UPDATE sort_results SET {set_clause} WHERE result_id=%s",
            list(updates.values()) + [result_id]
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Sort result not found")
        conn.commit()
        return {"message": "Updated"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@app.post("/api/snapshots/{snapshot_id}/flag")
def flag_snapshot(snapshot_id: int, body: dict):
    """Copy snapshot into dataset folder and record label."""
    label = (body.get("label") or "").lower()
    if label not in DATASET_CLASSES:
        raise HTTPException(status_code=400, detail=f"label must be one of {DATASET_CLASSES}")
    conn = get_db("production")
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT filename, dataset_label FROM inspection_snapshots WHERE snapshot_id=%s", (snapshot_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Snapshot not found")

        # Remove from old dataset folder if previously flagged
        old_label = row["dataset_label"]
        if old_label and old_label != label:
            old_path = os.path.join(DATASET_DIR, old_label, row["filename"])
            if os.path.exists(old_path):
                os.remove(old_path)

        # Copy into new class folder
        dest_dir = os.path.join(DATASET_DIR, label)
        os.makedirs(dest_dir, exist_ok=True)
        src = os.path.join(SNAPSHOTS_DIR, row["filename"])
        dst = os.path.join(dest_dir, row["filename"])
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)

        cursor.execute("UPDATE inspection_snapshots SET dataset_label=%s WHERE snapshot_id=%s", (label, snapshot_id))
        conn.commit()
        return {"message": f"Flagged as {label}", "dataset_label": label}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@app.post("/api/snapshots/{snapshot_id}/unflag")
def unflag_snapshot(snapshot_id: int):
    """Remove from dataset folder and clear label."""
    conn = get_db("production")
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT filename, dataset_label FROM inspection_snapshots WHERE snapshot_id=%s", (snapshot_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        if row["dataset_label"]:
            old_path = os.path.join(DATASET_DIR, row["dataset_label"], row["filename"])
            if os.path.exists(old_path):
                os.remove(old_path)
        cursor.execute("UPDATE inspection_snapshots SET dataset_label=NULL WHERE snapshot_id=%s", (snapshot_id,))
        conn.commit()
        return {"message": "Unflagged"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@app.post("/api/snapshots/batch-flag")
def batch_flag_snapshots(body: dict):
    """Add selected snapshots to dataset using each snapshot's detected_class as the label."""
    ids = body.get("snapshot_ids", [])
    if not ids:
        raise HTTPException(status_code=400, detail="No snapshot_ids provided")
    conn = get_db("production")
    cursor = conn.cursor(dictionary=True)
    try:
        ph = ",".join(["%s"] * len(ids))
        cursor.execute(f"""
            SELECT s.snapshot_id, s.filename, s.dataset_label,
                   sr.detected_class
            FROM inspection_snapshots s
            LEFT JOIN sort_results sr ON s.result_id = sr.result_id
            WHERE s.snapshot_id IN ({ph})
        """, ids)
        rows = cursor.fetchall()
        skipped = 0
        for row in rows:
            # Prefer manually set dataset_label; fall back to detected_class
            if row["dataset_label"] in DATASET_CLASSES:
                label = row["dataset_label"]
            else:
                raw = (row["detected_class"] or "").lower()
                label = raw.replace("class_", "") if raw.startswith("class_") else raw
            if label not in DATASET_CLASSES:
                skipped += 1
                continue
            old = row["dataset_label"]
            if old and old != label:
                old_path = os.path.join(DATASET_DIR, old, row["filename"])
                if os.path.exists(old_path):
                    os.remove(old_path)
            dest_dir = os.path.join(DATASET_DIR, label)
            os.makedirs(dest_dir, exist_ok=True)
            src = os.path.join(SNAPSHOTS_DIR, row["filename"])
            dst = os.path.join(dest_dir, row["filename"])
            if os.path.exists(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)
            cursor.execute(
                "UPDATE inspection_snapshots SET dataset_label=%s WHERE snapshot_id=%s",
                (label, row["snapshot_id"])
            )
        conn.commit()
        added = len(rows) - skipped
        msg = f"Added {added} snapshot(s) to dataset"
        if skipped:
            msg += f" ({skipped} skipped — no detected class)"
        return {"message": msg}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@app.post("/api/snapshots/batch-delete")
def batch_delete_snapshots(body: dict):
    ids = body.get("snapshot_ids", [])
    if not ids:
        raise HTTPException(status_code=400, detail="No snapshot_ids provided")
    conn = get_db("production")
    cursor = conn.cursor(dictionary=True)
    try:
        ph = ",".join(["%s"] * len(ids))
        cursor.execute(f"SELECT snapshot_id, filename, dataset_label FROM inspection_snapshots WHERE snapshot_id IN ({ph})", ids)
        rows = cursor.fetchall()
        cursor.execute(f"DELETE FROM inspection_snapshots WHERE snapshot_id IN ({ph})", ids)
        conn.commit()
        for row in rows:
            filepath = os.path.join(SNAPSHOTS_DIR, row["filename"])
            if os.path.exists(filepath):
                os.remove(filepath)
            if row["dataset_label"]:
                ds_path = os.path.join(DATASET_DIR, row["dataset_label"], row["filename"])
                if os.path.exists(ds_path):
                    os.remove(ds_path)
        return {"message": f"Deleted {len(rows)} snapshots"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

# ── Training endpoints ────────────────────────────────────────────────────────

class TrainConfig(BaseModel):
    epochs:      int   = 50
    lr:          float = 0.001
    batch_size:  int   = 16
    dense_units: int   = 128
    alpha:       float = 0.35
    val_split:   float = 0.15
    augment:       bool  = False
    aug_intensity: float = 1.0
    optimizer:     str   = 'adam'

def _run_training(config: TrainConfig):
    global _train_running, _train_exit_code
    _train_log.clear()
    _train_running = True
    _train_exit_code = None
    try:
        proc = subprocess.Popen(
            [
                TRAIN_PYTHON, TRAIN_SCRIPT,
                '--epochs',      str(config.epochs),
                '--lr',          str(config.lr),
                '--batch-size',  str(config.batch_size),
                '--dense-units', str(config.dense_units),
                '--alpha',       str(config.alpha),
                '--val-split',   str(config.val_split),
                '--aug-intensity', str(config.aug_intensity),
                '--optimizer',    config.optimizer,
                *(['--augment'] if config.augment else []),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=os.path.dirname(TRAIN_SCRIPT),
        )
        for line in proc.stdout:
            # Keras progress bars use \r to overwrite lines. Keep only the last
            # frame (what a terminal would show) so each entry is a clean line.
            last_frame = line.rstrip('\n').split('\r')[-1].strip()
            if last_frame:
                _train_log.append(last_frame)
        proc.wait()
        _train_exit_code = proc.returncode
    except Exception as e:
        _train_log.append(f"ERROR: {e}")
        _train_exit_code = -1
    finally:
        _train_running = False

@app.get("/dataset-images/{cls}/{filename}")
def serve_dataset_image(cls: str, filename: str):
    if cls not in DATASET_CLASSES:
        raise HTTPException(status_code=400, detail="Invalid class")
    if os.sep in filename or '/' in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = os.path.join(DATASET_DIR, cls, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, headers={"Cache-Control": "no-store"})

@app.get("/api/dataset")
def get_dataset():
    """Returns file list per class from the local image_dataset directory."""
    result = {}
    for cls in DATASET_CLASSES:
        cls_dir = os.path.join(DATASET_DIR, cls)
        if os.path.isdir(cls_dir):
            files = sorted(f for f in os.listdir(cls_dir)
                           if f.lower().endswith(('.jpg', '.jpeg', '.png')))
            result[cls] = files
        else:
            result[cls] = []
    return result

@app.post("/api/dataset/{cls}/save-frame")
def save_dataset_frame(cls: str):
    """Grab the current cam frame and save it directly into the dataset folder."""
    import urllib.request
    if cls not in DATASET_CLASSES:
        raise HTTPException(status_code=400, detail="Invalid class")
    dest_dir = os.path.join(DATASET_DIR, cls)
    os.makedirs(dest_dir, exist_ok=True)
    try:
        with urllib.request.urlopen("http://localhost:5000/single_frame", timeout=3) as resp:
            data = resp.read()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Camera server unreachable: {e}")
    from datetime import datetime
    filename = f"manual_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]}.jpg"
    with open(os.path.join(dest_dir, filename), "wb") as f:
        f.write(data)
    # Also copy to snapshots dir so it appears in the dashboard Snapshots tab
    with open(os.path.join(SNAPSHOTS_DIR, filename), "wb") as f:
        f.write(data)
    return {"message": f"Saved to {cls}/{filename}", "filename": filename}

class CropRequest(BaseModel):
    x: float  # left edge as fraction of image width  (0–1)
    y: float  # top  edge as fraction of image height (0–1)
    w: float  # crop width  as fraction of image width
    h: float  # crop height as fraction of image height

@app.post("/api/dataset/{cls}/{filename}/crop")
def crop_dataset_image(cls: str, filename: str, req: CropRequest):
    from PIL import Image
    if cls not in DATASET_CLASSES:
        raise HTTPException(status_code=400, detail="Invalid class")
    if os.sep in filename or '/' in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = os.path.join(DATASET_DIR, cls, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    with Image.open(path) as img:
        iw, ih = img.size
        left   = int(req.x * iw)
        top    = int(req.y * ih)
        right  = int((req.x + req.w) * iw)
        bottom = int((req.y + req.h) * ih)
        left, right  = max(0, left),  min(iw, right)
        top,  bottom = max(0, top),   min(ih, bottom)
        cropped = img.crop((left, top, right, bottom)).resize((224, 224), Image.LANCZOS)
        cropped.save(path, quality=95)
    return {"message": f"Cropped and saved {filename}"}

@app.delete("/api/dataset/{cls}/{filename}")
def delete_dataset_file(cls: str, filename: str):
    if cls not in DATASET_CLASSES:
        raise HTTPException(status_code=400, detail="Invalid class")
    # Basic path safety — filename must not contain separators
    if os.sep in filename or '/' in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = os.path.join(DATASET_DIR, cls, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    os.remove(path)
    return {"message": f"Deleted {cls}/{filename}"}

@app.post("/api/train/start")
def train_start(config: TrainConfig = None):
    global _train_running
    if _train_running:
        raise HTTPException(status_code=409, detail="Training already running")
    cfg = config or TrainConfig()
    threading.Thread(target=_run_training, args=(cfg,), daemon=True).start()
    return {"message": "Training started"}

@app.get("/api/train/status")
def train_status():
    return {
        "running":   _train_running,
        "exit_code": _train_exit_code,
        "log":       _train_log,
    }

@app.delete("/api/snapshots/{snapshot_id}")
def delete_snapshot(snapshot_id: int):
    conn = get_db("production")
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT filename FROM inspection_snapshots WHERE snapshot_id=%s", (snapshot_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        cursor.execute("DELETE FROM inspection_snapshots WHERE snapshot_id=%s", (snapshot_id,))
        conn.commit()
        filepath = os.path.join(SNAPSHOTS_DIR, row["filename"])
        if os.path.exists(filepath):
            os.remove(filepath)
        return {"message": "Snapshot deleted"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()