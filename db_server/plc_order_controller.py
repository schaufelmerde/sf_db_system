"""
PLC Order Controller
====================
Event-driven order queue manager for the PLC buffer.

DB change events are pushed by the FastAPI middleware over WebSocket.
B710 and B701 are hardware signals polled on a fixed interval.

Buffer layout (Mitsubishi MELSEC — MC Protocol):
  D0 / D1     → Slot 0: current IN_PROGRESS order (low word / high word)
  D2 / D3     → Slot 1: next QUEUED order          (low word / high word)
  D100 / D101 → IN_PROGRESS part IDs
  D200 / D201 → QUEUED part IDs

  B710        → Shift trigger: promote QUEUED → IN_PROGRESS, shift part IDs
  B701        → Completion trigger: mark IN_PROGRESS order as COMPLETE
  D1000/D1001 → Completed order ID written back by PLC (low / high word)

Order ID encoding:
  'P000000001'  →  integer 1
  low_word  = value & 0xFFFF          → D0 (or D2)
  high_word = (value >> 16) & 0xFFFF  → D1 (or D3)
"""

import asyncio
import json
import logging
import time

import mysql.connector
import pymcprotocol
import websockets

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

DB_CONFIG = {
    'host':     'localhost',
    'user':     'root',
    'password': '1234',
    'database': 'sf_order',
    'use_pure': True,
}

DB_CONFIG_INV = {
    'host':     'localhost',
    'user':     'root',
    'password': '1234',
    'database': 'sf_inventory',
    'use_pure': True,
}

_ORDER_TO_SHIP_STATUS = {
    'IN_PROGRESS': 'BUILDING',
    'COMPLETE':    'FINISHED',
    'PENDING':     'PLANNING',
    'QUEUED':      'PLANNING',
}

PLC_HOST    = '192.168.3.110'
PLC_PORT    = 1026
WS_URI      = 'ws://localhost:8000/ws/orders'
POLL_SEC    = 0.5               # B701 polling interval

REG_SLOT0_LOW  = 0    # D0
REG_SLOT0_HIGH = 1    # D1
REG_SLOT1_LOW  = 2    # D2
REG_SLOT1_HIGH = 3    # D3
REG_CONFIRM_L  = 1000 # D1000
REG_CONFIRM_H  = 1001 # D1001
REG_PART1      = 100  # D100  — IN_PROGRESS part ids
REG_PART2      = 101  # D101
REG_PART1_Q    = 200  # D200  — QUEUED part ids
REG_PART2_Q    = 201  # D201
BIT_COMPLETE   = 0x701
BIT_SHIFT      = 0x710  # B710 — PLC signals: promote queued → in-progress

# ── Shared state ──────────────────────────────────────────────────────────────

slot = [None, None]   # slot[0] = IN_PROGRESS, slot[1] = QUEUED
plc: pymcprotocol.Type3E | None = None

# ── Helpers ───────────────────────────────────────────────────────────────────

def order_to_words(order_id: str) -> tuple[int, int]:
    value = int(order_id[1:])
    return value & 0xFFFF, (value >> 16) & 0xFFFF   # low, high

def words_to_order(low: int, high: int) -> str:
    return f'P{((high << 16) | low):09d}'

def get_db():
    return mysql.connector.connect(**DB_CONFIG)

# ── Database ──────────────────────────────────────────────────────────────────

def fetch_next_order(exclude_ids: list[str] | None = None) -> str | None:
    if exclude_ids is None:
        exclude_ids = []
    conn = get_db()
    cur = conn.cursor()
    try:
        if exclude_ids:
            ph = ','.join(['%s'] * len(exclude_ids))
            cur.execute(
                f"SELECT order_id FROM orders WHERE status IN ('PENDING','QUEUED') "
                f"AND order_id NOT IN ({ph}) "
                f"ORDER BY priority ASC, created_at ASC LIMIT 1",
                exclude_ids,
            )
        else:
            cur.execute(
                "SELECT order_id FROM orders WHERE status IN ('PENDING','QUEUED') "
                "ORDER BY priority ASC, created_at ASC LIMIT 1"
            )
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()

def fetch_part_ids(order_id: str) -> tuple[int, int]:
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT part1_id, part2_id FROM order_items WHERE order_id=%s LIMIT 1",
            (order_id,)
        )
        row = cur.fetchone()
        if row is None:
            return 0, 0
        def parse(pid) -> int:
            if pid is None:
                return 0
            return int(str(pid).split('-')[-1])
        return parse(row[0]), parse(row[1])
    finally:
        conn.close()

def set_status(order_id: str, status: str):
    ship_id = None
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE orders SET status=%s WHERE order_id=%s", (status, order_id))
        cur.execute("SELECT ship_id FROM orders WHERE order_id=%s", (order_id,))
        row = cur.fetchone()
        ship_id = row[0] if row else None
        conn.commit()
        log.info(f'Order {order_id} → {status}')
    finally:
        conn.close()

    ship_status = _ORDER_TO_SHIP_STATUS.get(status)
    if ship_id and ship_status:
        inv_conn = mysql.connector.connect(**DB_CONFIG_INV)
        inv_cur = inv_conn.cursor()
        try:
            inv_cur.execute("UPDATE ships SET status=%s WHERE ship_id=%s", (ship_status, ship_id))
            inv_conn.commit()
            log.info(f'Ship {ship_id} → {ship_status}')
        finally:
            inv_conn.close()

# ── PLC ───────────────────────────────────────────────────────────────────────

def connect_plc() -> pymcprotocol.Type3E:
    while True:
        try:
            p = pymcprotocol.Type3E()
            p.soc_timeout = 5.0
            p.connect(PLC_HOST, PLC_PORT)
            p.setaccessopt(commtype='binary')
            log.info(f'Connected to PLC at {PLC_HOST}:{PLC_PORT}')
            return p
        except Exception as e:
            log.warning(f'PLC connect failed ({e}) — retrying in 5s...')
            time.sleep(5)

def write_slot(idx: int, order_id: str):
    low, high = order_to_words(order_id)
    base = REG_SLOT0_LOW if idx == 0 else REG_SLOT1_LOW
    plc.batchwrite_wordunits(headdevice=f'D{base}', values=[low, high])
    log.info(f'PLC slot {idx} (D{base}/D{base+1}) ← {order_id}')

def clear_slot(idx: int):
    base = REG_SLOT0_LOW if idx == 0 else REG_SLOT1_LOW
    plc.batchwrite_wordunits(headdevice=f'D{base}', values=[0, 0])
    log.info(f'PLC slot {idx} cleared')

def write_part_ids(order_id: str):
    p1, p2 = fetch_part_ids(order_id)
    plc.batchwrite_wordunits(headdevice=f'D{REG_PART1}', values=[p1, p2])
    log.info(f'PLC D{REG_PART1}/D{REG_PART2} ← part1={p1} part2={p2} (order {order_id})')

def write_queued_part_ids(order_id: str):
    p1, p2 = fetch_part_ids(order_id)
    plc.batchwrite_wordunits(headdevice=f'D{REG_PART1_Q}', values=[p1, p2])
    log.info(f'PLC D{REG_PART1_Q}/D{REG_PART2_Q} ← part1={p1} part2={p2} (queued {order_id})')

def clear_queued_part_ids():
    plc.batchwrite_wordunits(headdevice=f'D{REG_PART1_Q}', values=[0, 0])
    log.info(f'PLC D{REG_PART1_Q}/D{REG_PART2_Q} cleared')

def read_b701() -> bool:
    bits = plc.batchread_bitunits(headdevice=f'B{BIT_COMPLETE:X}', readsize=1)
    return bits[0] == 1

def reset_b701():
    plc.batchwrite_bitunits(headdevice=f'B{BIT_COMPLETE:X}', values=[0])
    log.info('B701 reset')

def read_b710() -> bool:
    bits = plc.batchread_bitunits(headdevice=f'B{BIT_SHIFT:X}', readsize=1)
    return bits[0] == 1

def reset_b710():
    plc.batchwrite_bitunits(headdevice=f'B{BIT_SHIFT:X}', values=[0])
    log.info('B710 reset')

def read_confirmed_order() -> str:
    words = plc.batchread_wordunits(headdevice=f'D{REG_CONFIRM_L}', readsize=2)
    return words_to_order(words[0], words[1])

# ── Queue helpers ─────────────────────────────────────────────────────────────

def fill_slots():
    """Fill any empty slots from the DB."""
    if not slot[0]:
        slot[0] = fetch_next_order(exclude_ids=[s for s in slot if s])
        if slot[0]:
            write_slot(0, slot[0])
            set_status(slot[0], 'IN_PROGRESS')
            write_part_ids(slot[0])
            log.info(f'Slot 0 loaded: {slot[0]}')

    if not slot[1]:
        slot[1] = fetch_next_order(exclude_ids=[s for s in slot if s])
        if slot[1]:
            write_slot(1, slot[1])
            set_status(slot[1], 'QUEUED')
            write_queued_part_ids(slot[1])
            log.info(f'Slot 1 loaded: {slot[1]}')
        else:
            clear_queued_part_ids()

def handle_shift():
    """B710 — promote queued order to in-progress slot, shift part IDs D200/D201 → D100/D101."""
    if not slot[1]:
        log.warning('B710 triggered but no queued order in slot 1 — ignoring')
        return

    if slot[0]:
        log.warning(f'B710 fired but slot[0] ({slot[0]}) not yet completed — marking COMPLETE')
        set_status(slot[0], 'COMPLETE')
        clear_slot(0)

    slot[0] = slot[1]
    slot[1] = None
    write_slot(0, slot[0])
    set_status(slot[0], 'IN_PROGRESS')
    write_part_ids(slot[0])       # D100/D101 ← promoted order's parts
    clear_queued_part_ids()       # D200/D201 cleared until fill_slots loads next
    log.info(f'Slot promoted on B710: {slot[0]}')

    fill_slots()                  # loads next QUEUED order into slot[1] + D200/D201

def handle_completion(confirmed: str):
    """B701 — mark current in-progress order as complete."""
    if confirmed != slot[0]:
        log.warning(f'Confirmed {confirmed} does not match slot 0 ({slot[0]}) — ignoring')
        return

    set_status(slot[0], 'COMPLETE')
    log.info(f'Order {slot[0]} marked COMPLETE via B701')
    slot[0] = None
    clear_slot(0)

def handle_deletion(order_id: str):
    if order_id == slot[1]:
        log.info(f'Queued order {order_id} deleted — clearing slot 1')
        clear_slot(1)
        clear_queued_part_ids()
        slot[1] = None
        fill_slots()
    elif order_id == slot[0]:
        log.info(f'Active order {order_id} deleted — promoting slot 1')
        if slot[1]:
            slot[0] = slot[1]
            slot[1] = None
            write_slot(0, slot[0])
            set_status(slot[0], 'IN_PROGRESS')
            write_part_ids(slot[0])
            clear_queued_part_ids()
        else:
            clear_slot(0)
            slot[0] = None
        fill_slots()

# ── Coroutines ────────────────────────────────────────────────────────────────

async def plc_poller():
    """Polls B710 and B701 every POLL_SEC. Reconnects on PLC timeout/error."""
    global plc
    while True:
        try:
            if read_b701():
                confirmed = slot[0]
                log.info(f'B701 triggered — completing slot 0: {confirmed}')
                handle_completion(confirmed)
                reset_b701()

            if read_b710():
                log.info('B710 triggered — shifting queued → in-progress')
                handle_shift()
                reset_b710()
        except (TimeoutError, OSError) as e:
            log.warning(f'PLC error ({e}) — reconnecting...')
            plc = await asyncio.get_event_loop().run_in_executor(None, connect_plc)
        except Exception as e:
            log.error(f'PLC poller error: {e}')
        await asyncio.sleep(POLL_SEC)


async def ws_listener():
    """Listens for order events from the FastAPI middleware."""
    while True:
        try:
            async with websockets.connect(WS_URI) as ws:
                log.info(f'Connected to API WebSocket at {WS_URI}')
                async for message in ws:
                    try:
                        event = json.loads(message)
                        etype = event.get('event')
                        oid   = event.get('order_id')

                        if etype == 'order_created':
                            log.info(f'Event: order_created {oid}')
                            fill_slots()
                        elif etype == 'order_deleted':
                            log.info(f'Event: order_deleted {oid}')
                            handle_deletion(oid)
                        elif etype == 'order_updated':
                            log.info(f'Event: order_updated {oid} status={event.get("status")}')
                            # If a status was manually set to CANCELLED/ON_HOLD, treat as deletion
                            if event.get('status') in ('CANCELLED', 'ON_HOLD'):
                                handle_deletion(oid)
                    except Exception as e:
                        log.error(f'Event handling error: {e}')
        except Exception as e:
            log.warning(f'WebSocket disconnected ({e}) — retrying in 3s...')
            await asyncio.sleep(3)


async def main():
    global plc

    plc = await asyncio.get_event_loop().run_in_executor(None, connect_plc)

    # Resume any IN_PROGRESS order from before restart
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT order_id FROM orders WHERE status='IN_PROGRESS' "
        "ORDER BY created_at ASC LIMIT 1"
    )
    row = cur.fetchone()
    conn.close()

    if row:
        slot[0] = row[0]
        write_slot(0, slot[0])
        write_part_ids(slot[0])
        log.info(f'Resumed IN_PROGRESS: {slot[0]}')

    # Reset stale QUEUED orders back to PENDING so fill_slots picks them up correctly
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET status='PENDING' WHERE status='QUEUED'")
    conn.commit()
    conn.close()
    log.info('Stale QUEUED orders reset to PENDING')

    fill_slots()
    log.info(f'Initial state — slot0: {slot[0]}  slot1: {slot[1]}')

    await asyncio.gather(plc_poller(), ws_listener())


if __name__ == '__main__':
    asyncio.run(main())
