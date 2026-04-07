from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import mysql.connector
from pydantic import BaseModel
import shutil, uuid, os

SNAPSHOTS_DIR = os.path.join(os.path.dirname(__file__), "snapshots")
os.makedirs(SNAPSHOTS_DIR, exist_ok=True)

app = FastAPI()
app.mount("/snapshots", StaticFiles(directory=SNAPSHOTS_DIR), name="snapshots")

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
        host="192.168.3.112",
        user="remote_user",
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
        "ALTER TABLE sort_results DROP COLUMN snapshot_path",
        """CREATE TABLE IF NOT EXISTS inspection_snapshots (
            snapshot_id   INT          NOT NULL AUTO_INCREMENT,
            result_id     INT          NOT NULL,
            filename      VARCHAR(255) NOT NULL,
            snapshot_type ENUM('INITIAL','RECHECK','DEFECT_DETAIL','PASS') DEFAULT 'INITIAL',
            taken_at      DATETIME(3)  DEFAULT CURRENT_TIMESTAMP(3),
            notes         VARCHAR(200),
            PRIMARY KEY (snapshot_id),
            INDEX idx_result (result_id)
        )""",
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
            pass
    conn.close()

    inv_conn = get_db("inventory")
    inv_cur = inv_conn.cursor()
    for ddl in [
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
            order_cur.execute("DELETE FROM orders WHERE ship_id=%s", (ship_id,))
            order_conn.commit()
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
        next_id = str(cursor.fetchone()[0]).zfill(8)

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
        sql = """
            UPDATE customers
            SET company_name=%s, contact_name=%s, phone=%s, email=%s
            WHERE customer_id=%s
        """
        cursor.execute(sql, (
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
            cursor.execute("DELETE FROM orders WHERE customer_id=%s", (customer_id,))
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
        cycles = {}
        for r in rows:
            rid = r['result_id']
            if rid not in cycles:
                cycles[rid] = {
                    'result_id':      rid,
                    'result_status':  r['result_status'],
                    'inspected_at':   str(r['inspected_at']) if r['inspected_at'] else None,
                    'detected_class': r['detected_class'],
                    'confidence':     float(r['confidence']) if r['confidence'] else None,
                    'cycle_time_sec': float(r['cycle_time_sec']) if r['cycle_time_sec'] else None,
                    'snapshots':      [],
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
    return {"message": "Order deleted successfully"}

@app.post("/api/orders/generate")
def generate_random_orders(data: dict):
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
            due_date = (date.today() + timedelta(days=random.randint(30, 180))).isoformat()
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
        return {"message": "Order created successfully", "order_id": order_id, "ship_id": ship_id}
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
    conn = get_db("production")
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT
                s.snapshot_id, s.result_id, s.filename, s.snapshot_type,
                s.taken_at, s.notes,
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