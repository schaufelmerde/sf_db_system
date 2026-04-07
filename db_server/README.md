[한국어 버전 README](README.ko.md)

# SF DB Server

Smart Factory database middleware and dashboard for the auto-sorting system.

---

## Project Structure

```
db_server/
├── main.py                  # FastAPI middleware (local DB)
├── main_remote.py           # FastAPI middleware (remote DB at 192.168.3.112)
├── db_setup.py              # Creates all databases and tables
├── db_schema_design.md      # Full schema reference with notes
├── generate_schema_sheet.py # Exports schema to schema_overview.xlsx
├── requirements.txt         # Python dependencies
├── install.bat              # One-time setup script
├── start.bat                # Launch script (local DB)
├── start_remote.bat         # Launch script (remote DB)
├── snapshots/               # Inspection snapshot images (served via API)
└── sf-dashboard/            # React dashboard (Vite)
```

---

## First-Time Setup

> Run once on a new machine. Requires Python and Node.js on PATH, and admin privileges to start MySQL.

Right-click `install.bat` → **Run as administrator**

This will:
1. Delete and recreate the `dbvenv` Python virtual environment
2. Start the MySQL81 service and wait until it is ready
3. Install Python dependencies from `requirements.txt`
4. Install Node packages for `sf-dashboard`
5. Run `db_setup.py` to create all databases and tables

---

## Running the Application

### Local DB mode
Double-click `start.bat` (requires admin for MySQL service start)

### Remote DB mode
Double-click `start_remote.bat`
Connects to MySQL at `192.168.3.112` using `main_remote.py`.

Both scripts open:
- **API** → `http://localhost:8000`
- **Dashboard** → `http://localhost:5173`

---

## Databases

| Database | Purpose |
|---|---|
| `sf_order` | Customers, orders, order items |
| `sf_inventory` | Ships, parts, inventory |
| `sf_production` | Sort results, inspection snapshots, sensor logs, robot logs |
| `sf_report` | Alarms, defect reports, shift summaries |

See `db_schema_design.md` for full table and column definitions.
To generate a formatted Excel overview, run:
```
dbvenv\Scripts\python.exe generate_schema_sheet.py
```

---

## API Overview

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/init-data` | Ships, parts, customers |
| POST | `/api/customers` | Register customer |
| PUT | `/api/customers/{id}` | Update customer |
| DELETE | `/api/customers/{id}` | Delete customer |
| GET | `/api/parts/{id}` | Get part detail |
| POST | `/api/parts` | Add part |
| PUT | `/api/parts/{id}` | Update part |
| DELETE | `/api/parts/{id}` | Delete part |
| GET | `/api/ships` | List ships |
| POST | `/api/ships` | Add ship |
| PUT | `/api/ships/{id}` | Update ship |
| DELETE | `/api/ships/{id}` | Delete ship |
| GET | `/api/orders` | List orders |
| POST | `/api/orders` | Create order (auto-creates ship) |
| PUT | `/api/orders/{id}` | Update order |
| DELETE | `/api/orders/{id}` | Delete order |
| POST | `/api/sort-results/{id}/snapshot` | Upload inspection snapshot |
| GET | `/api/sort-results/{id}/snapshots` | List snapshots for a result |
| DELETE | `/api/snapshots/{id}` | Delete a snapshot |

Snapshot files are served statically at `/snapshots/{filename}`.

---

## Inspection Snapshot Workflow

Each weld inspection cycle creates a `sort_results` row. If the result is `NG`, the part is sent for rewelding and re-inspected, creating another `sort_results` row. Each cycle can have multiple images stored in `inspection_snapshots`:

```
order_item
  └── sort_results (cycle 1 — NG)
        └── inspection_snapshots: INITIAL, DEFECT_DETAIL
  └── sort_results (cycle 2 — PASS, after reweld)
        └── inspection_snapshots: RECHECK, PASS
```

Snapshot types: `INITIAL` · `RECHECK` · `DEFECT_DETAIL` · `PASS`
