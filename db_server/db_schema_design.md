# Smart Factory - Database Schema Design

> **Engine**: MySQL 8.0+
> **Charset**: utf8mb4
> **Project**: Smart Factory Auto Sorting System

---

## Overview — Multiple Database Strategy

| Database | Purpose | Used By |
|----------|---------|---------|
| `sf_order` | Customer orders & order-part mapping | Web App, HMI |
| `sf_production` | PLC signals, robot logs, sort results | Main Controller, SCADA |
| `sf_inventory` | Parts stock, ship assembly tracking | Web App, Dashboard |
| `sf_report` | Defects, alarms, shift summaries | HMI, Report Screen |

---

## Database 1: `sf_order`
> Manages customers, orders, and which parts each order requires.

```sql
CREATE DATABASE IF NOT EXISTS sf_order
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE sf_order;
```

### Table: `customers`
```sql
CREATE TABLE customers (
    customer_id     VARCHAR(20)     NOT NULL,           -- e.g. CUST-0001
    company_name    VARCHAR(100)    NOT NULL,
    contact_name    VARCHAR(50)     NOT NULL,
    phone           VARCHAR(20),
    email           VARCHAR(100),
    ship_id         VARCHAR(20),                        -- FK → sf_inventory.ships.ship_id
    created_at      DATETIME        DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (customer_id),
    INDEX idx_company (company_name)
);
```

### Table: `orders`
```sql
CREATE TABLE orders (
    order_id        VARCHAR(10)     NOT NULL,           -- e.g. P000000001 (P + 9 digits, fits PLC buffer)
    customer_id     VARCHAR(20)     NOT NULL,
    ship_id         VARCHAR(20)     NULL,               -- auto-set on order creation → sf_inventory.ships
    ship_type       VARCHAR(50)     NULL,               -- selected at order time (e.g. LNG Carrier)
    order_date      DATETIME        DEFAULT CURRENT_TIMESTAMP,
    due_date        DATE,
    status          ENUM(
                        'PENDING',
                        'QUEUED',
                        'IN_PROGRESS',
                        'COMPLETE',
                        'CANCELLED',
                        'ON_HOLD'
                    )               DEFAULT 'PENDING',
    priority        TINYINT         DEFAULT 3,          -- 1=Urgent ~ 5=Low
    total_qty       INT             DEFAULT 0,
    notes           TEXT,
    created_by      VARCHAR(50),
    plc_sent        BOOLEAN         DEFAULT FALSE,
    plc_sent_at     DATETIME,
    created_at      DATETIME        DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME        DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (order_id),
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    INDEX idx_customer  (customer_id),
    INDEX idx_status    (status),
    INDEX idx_due_date  (due_date)
);
```

### Table: `order_items`
> Each row is one assembly combination: **part1 + part2 → one ship sub-assembly**.
> Quantity per part is intentionally omitted — parts are heterogeneous (different types,
> dimensions, and counts per assembly), so a single qty field is meaningless here.
> The sort bin is determined at runtime by the production system based on detection results,
> not pre-assigned at order time.

```sql
CREATE TABLE order_items (
    item_id         INT             NOT NULL AUTO_INCREMENT,
    order_id        VARCHAR(20)     NOT NULL,
    part1_id        VARCHAR(20)     NOT NULL,           -- FK → sf_inventory.parts.part_id
    part2_id        VARCHAR(20)     NOT NULL,           -- FK → sf_inventory.parts.part_id
    item_status     ENUM(
                        'PENDING',
                        'IN_PROGRESS',
                        'COMPLETE',
                        'NG'
                    )               DEFAULT 'PENDING',
    completed_at    DATETIME,

    PRIMARY KEY (item_id),
    FOREIGN KEY (order_id) REFERENCES orders(order_id),
    FOREIGN KEY (part1_id) REFERENCES sf_inventory.parts(part_id),
    FOREIGN KEY (part2_id) REFERENCES sf_inventory.parts(part_id),

    INDEX idx_order   (order_id),
    INDEX idx_status  (item_status)
);
```

---

## Database 2: `sf_inventory`
> Manages parts stock, pricing, and ship assembly progress.

```sql
CREATE DATABASE IF NOT EXISTS sf_inventory
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE sf_inventory;
```

### Table: `ships`
```sql
CREATE TABLE ships (
    ship_id         VARCHAR(20)     NOT NULL,           -- e.g. SHIP-001
    ship_name       VARCHAR(100)    NOT NULL,
    ship_type       VARCHAR(50),                        -- LNG Carrier, Container, Tanker
    total_parts_req INT             DEFAULT 0,
    parts_completed INT             DEFAULT 0,
    status          ENUM('PLANNING','BUILDING','LAUNCHED','COMPLETE') DEFAULT 'BUILDING',
    start_date      DATE,
    target_date     DATE,

    PRIMARY KEY (ship_id),
    INDEX idx_status (status)
);
```

### Table: `parts`
```sql
CREATE TABLE parts (
    part_id         VARCHAR(20)     NOT NULL,           -- e.g. PART-001
    part_name       VARCHAR(100)    NOT NULL,
    part_category   VARCHAR(50),                        -- Hull Block, Pipe Spool, Bracket ...
    unit_cost       DECIMAL(12,2)   DEFAULT 0.00,       -- KRW
    unit_weight_kg  DECIMAL(8,2),
    sort_bin        TINYINT,                            -- default sort bin (1/2/3)
    description     TEXT,
    created_at      DATETIME        DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (part_id)
);
```

### Table: `inventory`
```sql
CREATE TABLE inventory (
    inv_id          INT             NOT NULL AUTO_INCREMENT,
    part_id         VARCHAR(20)     NOT NULL,
    ship_id         VARCHAR(20)     NOT NULL,
    stock_qty       INT             DEFAULT 0,          -- current stock
    ordered_qty     INT             DEFAULT 0,          -- total ordered
    completed_qty   INT             DEFAULT 0,          -- completed by factory
    defect_qty      INT             DEFAULT 0,          -- NG count
    -- total_cost computed in application: completed_qty * parts.unit_cost
    -- (MySQL GENERATED columns do not support cross-row subqueries)
    last_updated    DATETIME        DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (inv_id),
    UNIQUE KEY uq_part_ship (part_id, ship_id),
    FOREIGN KEY (part_id) REFERENCES parts(part_id),
    FOREIGN KEY (ship_id) REFERENCES ships(ship_id)
);
```

---

## Database 3: `sf_production`
> Real-time PLC signals, robot coordinates, sort results from the factory floor.

```sql
CREATE DATABASE IF NOT EXISTS sf_production
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE sf_production;
```

### Table: `sort_results`
> One record per completed sort cycle.

```sql
CREATE TABLE sort_results (
    result_id       INT             NOT NULL AUTO_INCREMENT,
    order_id        VARCHAR(20),                        -- FK → sf_order.orders.order_id
    item_id         INT,                                -- FK → sf_order.order_items.item_id
    part1_id        VARCHAR(20),
    part2_id        VARCHAR(20),
    detected_class  VARCHAR(100),                       -- AI vision output label
    confidence      DECIMAL(5,2),                       -- 0.00 ~ 100.00 %
    sort_position   TINYINT,                            -- actual sort bin used (1/2/3)
    cycle_time_sec  DECIMAL(6,3),                       -- seconds
    status          ENUM('OK','NG') DEFAULT 'OK',
    ng_reason       VARCHAR(200),                       -- if NG: reason description
    plc_signal      VARCHAR(20),                        -- e.g. Y164

    -- TCP pose of the Indy 7 at the moment the part was released into the sort bin.
    -- Captured via Neuromeka IndySDK: get_task_pos() → [x, y, z, Rx, Ry, Rz].
    -- Stored to (1) verify the robot reached the correct placement pose,
    -- (2) diagnose NG events where the robot may have drifted or misplaced,
    -- (3) detect long-term mechanical drift by comparing actual vs. target poses over time.
    -- Units: x/y/z in mm, Rx/Ry/Rz in degrees (ZYZ Euler convention, Indy default).
    robot_x         DECIMAL(9,3),                       -- TCP position X (mm)
    robot_y         DECIMAL(9,3),                       -- TCP position Y (mm)
    robot_z         DECIMAL(9,3),                       -- TCP position Z (mm)
    robot_rx        DECIMAL(8,4),                       -- TCP rotation Rx (deg)
    robot_ry        DECIMAL(8,4),                       -- TCP rotation Ry (deg)
    robot_rz        DECIMAL(8,4),                       -- TCP rotation Rz (deg)

    created_at      DATETIME(3)     DEFAULT CURRENT_TIMESTAMP(3),

    PRIMARY KEY (result_id),
    INDEX idx_order      (order_id),
    INDEX idx_item       (item_id),
    INDEX idx_status     (status),
    INDEX idx_created    (created_at),
    INDEX idx_sort_pos   (sort_position)
);
```

### Table: `inspection_snapshots`
> One row per image captured during an inspection cycle. Multiple rows can reference the
> same `sort_results` row (multi-angle cameras, defect detail shots). Multiple `sort_results`
> rows per `order_item` track the full fail → reweld → reinspect history.

```sql
CREATE TABLE inspection_snapshots (
    snapshot_id     INT             NOT NULL AUTO_INCREMENT,
    result_id       INT             NOT NULL,           -- FK → sort_results.result_id
    filename        VARCHAR(255)    NOT NULL,           -- file stored in /snapshots/
    snapshot_type   ENUM(
                        'INITIAL',                     -- first inspection pass
                        'RECHECK',                     -- re-inspection after reweld
                        'DEFECT_DETAIL',               -- zoomed defect area
                        'PASS'                         -- final accepted image
                    )               DEFAULT 'INITIAL',
    taken_at        DATETIME(3)     DEFAULT CURRENT_TIMESTAMP(3),
    notes           VARCHAR(200),

    PRIMARY KEY (snapshot_id),
    INDEX idx_result (result_id)
);
```

### Table: `sensor_logs`
> PLC I/O state change events.

```sql
CREATE TABLE sensor_logs (
    log_id          BIGINT          NOT NULL AUTO_INCREMENT,
    device_addr     VARCHAR(10)     NOT NULL,           -- e.g. X103, Y30, M10
    device_type     ENUM('X','Y','M','T','B','D') NOT NULL,
    state_before    TINYINT,                            -- 0 or 1
    state_after     TINYINT,                            -- 0 or 1
    raw_value       INT,
    logged_at       DATETIME(3)     DEFAULT CURRENT_TIMESTAMP(3),

    PRIMARY KEY (log_id),
    INDEX idx_device  (device_addr),
    INDEX idx_time    (logged_at)
);
```

### Table: `robot_logs`
> Periodic robot coordinate snapshots.
> TCP pose via `get_task_pos()`, joint angles via `get_joint_pos()` — both from IndySDK.
> The Indy 7 is a 7-DOF arm; all 7 joint angles are recorded.

```sql
CREATE TABLE robot_logs (
    log_id          BIGINT          NOT NULL AUTO_INCREMENT,
    result_id       INT,                                -- FK → sort_results
    robot_state     ENUM('IDLE','MOVING','PICKING','PLACING','ERROR') DEFAULT 'IDLE',
    x               DECIMAL(9,3),                       -- TCP position X (mm)
    y               DECIMAL(9,3),                       -- TCP position Y (mm)
    z               DECIMAL(9,3),                       -- TCP position Z (mm)
    rx              DECIMAL(8,4),                       -- TCP rotation Rx (deg)
    ry              DECIMAL(8,4),                       -- TCP rotation Ry (deg)
    rz              DECIMAL(8,4),                       -- TCP rotation Rz (deg)
    joint1          DECIMAL(8,4),                       -- Joint angles in degrees (Indy 7: 7-DOF)
    joint2          DECIMAL(8,4),
    joint3          DECIMAL(8,4),
    joint4          DECIMAL(8,4),
    joint5          DECIMAL(8,4),
    joint6          DECIMAL(8,4),
    joint7          DECIMAL(8,4),                       -- 7th joint — unique to Indy 7
    gripper_open    BOOLEAN         DEFAULT TRUE,
    logged_at       DATETIME(3)     DEFAULT CURRENT_TIMESTAMP(3),

    PRIMARY KEY (log_id),
    INDEX idx_time   (logged_at),
    INDEX idx_result (result_id)
);
```

---

## Database 4: `sf_report`
> Defect analysis, alarm history, and shift/daily summaries.

```sql
CREATE DATABASE IF NOT EXISTS sf_report
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE sf_report;
```

### Table: `alarms`
```sql
CREATE TABLE alarms (
    alarm_id        INT             NOT NULL AUTO_INCREMENT,
    alarm_level     ENUM('CRITICAL','WARNING','INFO') NOT NULL,
    source          ENUM('PLC','ROBOT','VISION','CONVEYOR','DB','SYSTEM') NOT NULL,
    error_code      VARCHAR(20),                        -- e.g. E-301, W-102
    message         TEXT            NOT NULL,
    device_tag      VARCHAR(20),                        -- e.g. X103, M1000
    is_active       BOOLEAN         DEFAULT TRUE,
    ack_by          VARCHAR(50),
    ack_at          DATETIME,
    resolved_at     DATETIME,
    triggered_at    DATETIME        DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (alarm_id),
    INDEX idx_level  (alarm_level),
    INDEX idx_active (is_active),
    INDEX idx_time   (triggered_at)
);
```

### Table: `defect_reports`
```sql
CREATE TABLE defect_reports (
    defect_id       INT             NOT NULL AUTO_INCREMENT,
    result_id       INT,                                -- FK → sf_production.sort_results
    order_id        VARCHAR(20),
    part1_id        VARCHAR(20),
    part2_id        VARCHAR(20),
    defect_type     ENUM(
                        'VISION_ERROR',
                        'ROBOT_MISPLACE',
                        'MATERIAL_DEFECT',
                        'SENSOR_ERROR',
                        'TIMEOUT',
                        'OTHER'
                    )               NOT NULL,
    expected_bin    TINYINT,
    actual_bin      TINYINT,
    confidence      DECIMAL(5,2),
    action_taken    ENUM('RE_SORT','MANUAL_FIX','SCRAPPED','PENDING') DEFAULT 'PENDING',
    resolved_by     VARCHAR(50),
    reported_at     DATETIME        DEFAULT CURRENT_TIMESTAMP,
    resolved_at     DATETIME,

    PRIMARY KEY (defect_id),
    INDEX idx_type   (defect_type),
    INDEX idx_order  (order_id)
);
```

### Table: `shift_summaries`
> One record per work shift (auto-generated at shift end).

```sql
CREATE TABLE shift_summaries (
    summary_id      INT             NOT NULL AUTO_INCREMENT,
    shift_date      DATE            NOT NULL,
    shift_num       TINYINT         NOT NULL,           -- 1=Day / 2=Evening / 3=Night
    start_time      DATETIME,
    end_time        DATETIME,
    total_cycles    INT             DEFAULT 0,
    ok_count        INT             DEFAULT 0,
    ng_count        INT             DEFAULT 0,
    defect_rate     DECIMAL(5,2)    GENERATED ALWAYS AS (
                        CASE WHEN total_cycles > 0
                             THEN ROUND(ng_count / total_cycles * 100, 2)
                             ELSE 0
                        END
                    ) STORED,
    avg_cycle_sec   DECIMAL(6,3),
    alarm_critical  INT             DEFAULT 0,
    alarm_warning   INT             DEFAULT 0,
    operator        VARCHAR(50),
    notes           TEXT,
    created_at      DATETIME        DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (summary_id),
    UNIQUE KEY uq_shift (shift_date, shift_num)
);
```

---

## Entity Relationship Summary

```
sf_order
├── customers ──────────────────────── ships (sf_inventory)
│       └── orders
│               └── order_items ─┬──── parts (sf_inventory)
│                                └──── parts (sf_inventory)
│
sf_production
├── sort_results ←── (order_id, item_id from sf_order)
│       ├── sensor_logs
│       └── robot_logs
│
sf_inventory
├── ships
├── parts
└── inventory (part × ship)
│
sf_report
├── alarms
├── defect_reports ←── (result_id from sf_production)
└── shift_summaries
```

---

## Sample Data

### Customers & Orders
```sql
-- Customers
INSERT INTO sf_order.customers VALUES
  ('CUST-001', 'Hyundai Heavy Industries', 'Kim T.H.', '051-123-4567', 'kth@hhi.com', 'SHIP-A', NOW(), NOW()),
  ('CUST-002', 'Samsung Heavy Industries', 'Park J.W.', '055-234-5678', 'pjw@shi.co.kr', 'SHIP-B', NOW(), NOW()),
  ('CUST-003', 'Daewoo Shipbuilding', 'Lee S.Y.', '055-345-6789', 'lsy@dsme.co.kr', 'SHIP-C', NOW(), NOW());

-- Orders
INSERT INTO sf_order.orders (order_id, customer_id, due_date, status, priority, total_qty, created_by, plc_sent)
VALUES
  ('ORD-2026-00001', 'CUST-001', '2026-04-15', 'IN_PROGRESS', 1, 200, 'Park T.H.', TRUE),
  ('ORD-2026-00002', 'CUST-002', '2026-04-20', 'QUEUED',      2, 150, 'Kim H.G.', FALSE),
  ('ORD-2026-00003', 'CUST-003', '2026-04-30', 'PENDING',     3, 300, 'Kim A.S.', FALSE);

-- Parts
INSERT INTO sf_inventory.parts (part_id, part_name, part_category, unit_cost, sort_bin)
VALUES
  ('PART-001', 'Hull Block A', 'Hull Block',  45000.00, 1),
  ('PART-002', 'Pipe Spool P-12', 'Pipe Spool', 12000.00, 2),
  ('PART-003', 'Bracket B-7',   'Bracket',    8500.00, 3);

-- Order Items (part1 + part2 combination → one ship sub-assembly per row)
INSERT INTO sf_order.order_items (order_id, part1_id, part2_id)
VALUES
  ('ORD-2026-00001', 'PART-001', 'PART-002'),
  ('ORD-2026-00002', 'PART-002', 'PART-003'),
  ('ORD-2026-00003', 'PART-001', 'PART-003');
```

---

## Connection Config (Python)

```python
# config/database.py
DATABASES = {
    "order": {
        "host": "192.168.3.xxx",
        "port": 3306,
        "user": "sf_user",
        "password": "your_password",
        "database": "sf_order",
    },
    "production": {
        "host": "192.168.3.xxx",
        "port": 3306,
        "user": "sf_user",
        "password": "your_password",
        "database": "sf_production",
    },
    "inventory": {
        "host": "192.168.3.xxx",
        "port": 3306,
        "user": "sf_user",
        "password": "your_password",
        "database": "sf_inventory",
    },
    "report": {
        "host": "192.168.3.xxx",
        "port": 3306,
        "user": "sf_user",
        "password": "your_password",
        "database": "sf_report",
    },
}
```

---

## Notes

- `order_items.part1_id` + `part2_id` represents the two-part combination that produces one ship sub-assembly.
  Quantities are not tracked per part at this level — parts are heterogeneous and the assembly count
  is managed at the `orders` level (`total_qty`) and tracked in `sf_inventory`.
  Extend to `part3_id` if needed later — no schema redesign required, just add a column.
- The sort bin for each item is assigned at runtime by the production system (written to `sort_results.sort_position`),
  not pre-defined in the order.
- `robot_logs` tracks all 7 joints of the Neuromeka Indy 7. `sort_results` stores only the TCP pose
  at release time — sufficient for placement verification without the overhead of full joint snapshots per cycle.
- Cross-database foreign keys are **not enforced by MySQL** at the engine level — handle referential integrity in the application layer (Python).
- `sensor_logs` and `robot_logs` will grow very fast. Consider **partitioning by month**:
  ```sql
  ALTER TABLE sensor_logs PARTITION BY RANGE (YEAR(logged_at) * 100 + MONTH(logged_at)) (
      PARTITION p202603 VALUES LESS THAN (202604),
      PARTITION p202604 VALUES LESS THAN (202605),
      PARTITION p_future VALUES LESS THAN MAXVALUE
  );
  ```
- Use `pymysql` or `mysql-connector-python` for the Python connection layer.
