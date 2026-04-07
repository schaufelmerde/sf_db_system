import mysql.connector
from mysql.connector import errorcode

# Configuration - Update with your actual credentials
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '1234',  # ENTER YOUR PASSWORD HERE
    'use_pure': True
}

# The SQL schema broken down by database
SCHEMA = {
    "sf_inventory": [
        """CREATE TABLE ships (
            ship_id         VARCHAR(20)     PRIMARY KEY,
            ship_name       VARCHAR(100)    NOT NULL,
            ship_type       VARCHAR(50),
            total_parts_req INT             DEFAULT 0,
            parts_completed INT             DEFAULT 0,
            status          ENUM('PLANNING','BUILDING','LAUNCHED','COMPLETE','FINISHED') DEFAULT 'PLANNING',
            start_date      DATE,
            target_date     DATE,
            INDEX idx_status (status)
        )""",
        """CREATE TABLE parts (
            part_id         VARCHAR(20)     PRIMARY KEY,
            part_name       VARCHAR(100)    NOT NULL,
            part_category   VARCHAR(50),
            unit_cost       DECIMAL(12,2)   DEFAULT 0.00,
            unit_weight_kg  DECIMAL(8,2),
            sort_bin        TINYINT,
            description     TEXT,
            created_at      DATETIME        DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE inventory (
            inv_id          INT             AUTO_INCREMENT PRIMARY KEY,
            part_id         VARCHAR(20)     NOT NULL,
            ship_id         VARCHAR(20)     NOT NULL,
            stock_qty       INT             DEFAULT 0,
            ordered_qty     INT             DEFAULT 0,
            completed_qty   INT             DEFAULT 0,
            defect_qty      INT             DEFAULT 0,
            last_updated    DATETIME        DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uq_part_ship (part_id, ship_id),
            FOREIGN KEY (part_id) REFERENCES parts(part_id),
            FOREIGN KEY (ship_id) REFERENCES ships(ship_id)
        )"""
    ],
    "sf_order": [
        """CREATE TABLE customers (
            customer_id     VARCHAR(20)     PRIMARY KEY,
            company_name    VARCHAR(100)    NOT NULL,
            contact_name    VARCHAR(50)     NOT NULL,
            phone           VARCHAR(20),
            email           VARCHAR(100),
            ship_id         VARCHAR(20),
            created_at      DATETIME        DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME        DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_company (company_name)
        )""",
        """CREATE TABLE orders (
            order_id        VARCHAR(10)     PRIMARY KEY,
            customer_id     VARCHAR(20)     NOT NULL,
            ship_id         VARCHAR(20)     NULL,
            ship_type       VARCHAR(50)     NULL,
            order_date      DATETIME        DEFAULT CURRENT_TIMESTAMP,
            due_date        DATE,
            status          ENUM('PENDING','QUEUED','IN_PROGRESS','COMPLETE','CANCELLED','ON_HOLD') DEFAULT 'PENDING',
            priority        TINYINT         DEFAULT 3,
            total_qty       INT             DEFAULT 0,
            notes           TEXT,
            created_by      VARCHAR(50),
            plc_sent        BOOLEAN         DEFAULT FALSE,
            plc_sent_at     DATETIME,
            created_at      DATETIME        DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME        DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
            INDEX idx_customer  (customer_id),
            INDEX idx_status    (status),
            INDEX idx_due_date  (due_date)
        )""",
        """CREATE TABLE order_items (
            item_id         INT             AUTO_INCREMENT PRIMARY KEY,
            order_id        VARCHAR(20)     NOT NULL,
            part1_id        VARCHAR(20)     NOT NULL,
            part2_id        VARCHAR(20)     NOT NULL,
            item_status     ENUM('PENDING','IN_PROGRESS','COMPLETE','NG') DEFAULT 'PENDING',
            completed_at    DATETIME,
            FOREIGN KEY (order_id) REFERENCES orders(order_id),
            INDEX idx_order  (order_id),
            INDEX idx_status (item_status)
        )"""
    ],
    "sf_production": [
        """CREATE TABLE sort_results (
            result_id       INT             AUTO_INCREMENT PRIMARY KEY,
            order_id        VARCHAR(20),
            item_id         INT,
            part1_id        VARCHAR(20),
            part2_id        VARCHAR(20),
            detected_class  VARCHAR(100),
            confidence      DECIMAL(5,2),
            sort_position   TINYINT,
            cycle_time_sec  DECIMAL(6,3),
            status          ENUM('OK','NG') DEFAULT 'OK',
            ng_reason       VARCHAR(200),
            plc_signal      VARCHAR(20),
            robot_x         DECIMAL(9,3),
            robot_y         DECIMAL(9,3),
            robot_z         DECIMAL(9,3),
            robot_rx        DECIMAL(8,4),
            robot_ry        DECIMAL(8,4),
            robot_rz        DECIMAL(8,4),
            created_at      DATETIME(3)     DEFAULT CURRENT_TIMESTAMP(3),
            INDEX idx_order     (order_id),
            INDEX idx_item      (item_id),
            INDEX idx_status    (status),
            INDEX idx_created   (created_at),
            INDEX idx_sort_pos  (sort_position)
        )""",
        """CREATE TABLE inspection_snapshots (
            snapshot_id     INT             AUTO_INCREMENT PRIMARY KEY,
            result_id       INT             NOT NULL,
            filename        VARCHAR(255)    NOT NULL,
            snapshot_type   ENUM('INITIAL','RECHECK','DEFECT_DETAIL','PASS') DEFAULT 'INITIAL',
            taken_at        DATETIME(3)     DEFAULT CURRENT_TIMESTAMP(3),
            notes           VARCHAR(200),
            INDEX idx_result (result_id)
        )""",
        """CREATE TABLE sensor_logs (
            log_id          BIGINT          AUTO_INCREMENT PRIMARY KEY,
            device_addr     VARCHAR(10)     NOT NULL,
            device_type     ENUM('X','Y','M','T','B','D') NOT NULL,
            state_before    TINYINT,
            state_after     TINYINT,
            raw_value       INT,
            logged_at       DATETIME(3)     DEFAULT CURRENT_TIMESTAMP(3),
            INDEX idx_device (device_addr),
            INDEX idx_time   (logged_at)
        )""",
        """CREATE TABLE robot_logs (
            log_id          BIGINT          AUTO_INCREMENT PRIMARY KEY,
            result_id       INT,
            robot_state     ENUM('IDLE','MOVING','PICKING','PLACING','ERROR') DEFAULT 'IDLE',
            x               DECIMAL(9,3),
            y               DECIMAL(9,3),
            z               DECIMAL(9,3),
            rx              DECIMAL(8,4),
            ry              DECIMAL(8,4),
            rz              DECIMAL(8,4),
            joint1          DECIMAL(8,4),
            joint2          DECIMAL(8,4),
            joint3          DECIMAL(8,4),
            joint4          DECIMAL(8,4),
            joint5          DECIMAL(8,4),
            joint6          DECIMAL(8,4),
            joint7          DECIMAL(8,4),
            gripper_open    BOOLEAN         DEFAULT TRUE,
            logged_at       DATETIME(3)     DEFAULT CURRENT_TIMESTAMP(3),
            INDEX idx_time   (logged_at),
            INDEX idx_result (result_id)
        )"""
    ],
    "sf_report": [
        """CREATE TABLE alarms (
            alarm_id        INT             AUTO_INCREMENT PRIMARY KEY,
            alarm_level     ENUM('CRITICAL','WARNING','INFO') NOT NULL,
            source          ENUM('PLC','ROBOT','VISION','CONVEYOR','DB','SYSTEM') NOT NULL,
            error_code      VARCHAR(20),
            message         TEXT            NOT NULL,
            device_tag      VARCHAR(20),
            is_active       BOOLEAN         DEFAULT TRUE,
            ack_by          VARCHAR(50),
            ack_at          DATETIME,
            resolved_at     DATETIME,
            triggered_at    DATETIME        DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_level  (alarm_level),
            INDEX idx_active (is_active),
            INDEX idx_time   (triggered_at)
        )"""
    ]
}

def run_setup():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()

        for db_name, tables in SCHEMA.items():
            print(f"--- Setting up Database: {db_name} ---")

            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name} CHARACTER SET utf8mb4")
            cursor.execute(f"USE {db_name}")

            for table_sql in tables:
                # Extract table name for clearer output
                table_name = table_sql.strip().split()[2]
                try:
                    cursor.execute(table_sql)
                    print(f"  Created: {table_name}")
                except mysql.connector.Error as err:
                    if err.errno == errorcode.ER_TABLE_EXISTS_ERROR:
                        print(f"  Exists:  {table_name}")
                    else:
                        print(f"  FAILED:  {table_name} — {err}")

        print("--- Inserting Sample Data ---")
        cursor.execute("INSERT IGNORE INTO sf_inventory.parts (part_id, part_name, sort_bin) VALUES ('PART-001', 'Hull Block A', 1)")
        cursor.execute("INSERT IGNORE INTO sf_order.customers (customer_id, company_name, contact_name) VALUES ('00000001', 'Hyundai Heavy', 'Kim T.H.')")

        conn.commit()
        print("Setup complete. Smart Factory DB is ready.")

    except mysql.connector.Error as err:
        print(f"Global Error: {err}")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == "__main__":
    run_setup()
