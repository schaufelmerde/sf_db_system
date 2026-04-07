import cv2
import numpy as np
import pymcprotocol
import time
import sys
import os
import urllib.request
import threading
import logging
import traceback
import mysql.connector
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "plc.log")),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger(__name__)

# --- 1. SETTINGS & PATHS ---
PLC_IP = "192.168.3.110"
PLC_PORT = 1025
CAM_URL = "http://localhost:5000/raw_frame"

# last stable model: tflite_11 (room lights off)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "models/tflite_90/model_unquant.tflite")
LABELS_PATH = os.path.join(BASE_DIR, "models/tflite_90/labels.txt")
SNAPSHOT_DIR = os.path.join(BASE_DIR, "snapshots")
os.makedirs(SNAPSHOT_DIR, exist_ok=True)

DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '1234',
    'database': 'sf_production',
    'use_pure': True
}

CONFIDENCE_THRESHOLD = 0.65
os.environ["OPENCV_VIDEOIO_PRIORITY_MSMF"] = "0"

# --- 2. DB SNAPSHOT SAVE ---
def save_snapshot_and_log(img, label, conf, res_val):
    try:
        ts = datetime.now()
        filename = f"snapshot_{ts.strftime('%Y%m%d_%H%M%S_%f')[:-3]}.jpg"
        filepath = os.path.join(SNAPSHOT_DIR, filename)
        cv2.imwrite(filepath, cv2.cvtColor(img, cv2.COLOR_RGB2BGR))

        status = "OK" if res_val == 1 else "NG"
        snapshot_type = "PASS" if res_val == 1 else "DEFECT_DETAIL"

        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # Resolve current active order from sf_order DB
        cursor.execute(
            "SELECT order_id FROM sf_order.orders WHERE status='IN_PROGRESS' "
            "ORDER BY created_at ASC LIMIT 1"
        )
        row = cursor.fetchone()
        active_order_id = row[0] if row else None

        # Insert sort result
        cursor.execute(
            "INSERT INTO sort_results (order_id, detected_class, confidence, status) VALUES (%s, %s, %s, %s)",
            (active_order_id, label, round(float(conf) * 100, 2), status)
        )
        result_id = cursor.lastrowid

        # Insert snapshot into inspection_snapshots
        cursor.execute(
            "INSERT INTO inspection_snapshots (result_id, filename, snapshot_type) VALUES (%s, %s, %s)",
            (result_id, filename, snapshot_type)
        )

        conn.commit()
        cursor.close()
        conn.close()
        log.info(f"Snapshot saved: {filename} (result_id={result_id})")
    except Exception as e:
        log.error(f"DB/snapshot error: {e}")

# --- 4. PRE-FLIGHT CHECKS ---
if not os.path.exists(MODEL_PATH) or not os.path.exists(LABELS_PATH):
    print(f"ERROR: Model or Labels not found at:\n{MODEL_PATH}\n{LABELS_PATH}")
    sys.exit()

# --- 3. INITIALIZE PLC ---
def connect_plc():
    global plc, plc_connected
    while True:
        try:
            log.info(f"Connecting to PLC at {PLC_IP}...")
            plc = pymcprotocol.Type3E()
            plc.connect(PLC_IP, PLC_PORT)
            plc_connected = True
            log.info("PLC Connected!")
            return
        except Exception as e:
            log.warning(f"PLC connection failed: {e}. Retrying in 3s...")
            time.sleep(3)

plc = pymcprotocol.Type3E()
plc_connected = False
connect_plc()

# --- 4. INITIALIZE AI MODEL (Fixed Interpreter Import) ---
try:
    from ai_edge_litert.interpreter import Interpreter
except ImportError:
    try:
        from tflite_runtime.interpreter import Interpreter
    except ImportError:
        from tensorflow.lite.python.interpreter import Interpreter

interpreter = Interpreter(model_path=MODEL_PATH)
interpreter.allocate_tensors()
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

with open(LABELS_PATH, "r") as f:
    class_names = [line.strip().split(' ', 1)[-1].lower() for line in f.readlines()]

# --- 5. CAMERA SETUP ---
cap = None
latest_frame = None
frame_lock = threading.Lock()
grabber_running = True

def frame_grabber():
    global cap, latest_frame, grabber_running
    while grabber_running:
        frame = None
        # Try class_cam server first
        try:
            with urllib.request.urlopen(CAM_URL, timeout=1) as resp:
                data = resp.read()
            arr = np.frombuffer(data, np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        except Exception:
            pass

        # Fall back to direct camera capture
        if frame is None:
            if cap is None:
                print("class_cam unavailable, opening camera directly...")
                cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            if cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    frame = None

        if frame is not None:
            with frame_lock:
                latest_frame = frame

grabber_thread = threading.Thread(target=frame_grabber, daemon=True)
grabber_thread.start()

print(f"Connecting to camera server at {CAM_URL}...")
for i in range(15):
    time.sleep(1)
    with frame_lock:
        if latest_frame is not None:
            print("Camera ready.")
            break
    print(f"Waiting for camera... ({i+1}/15)")
else:
    print("CRITICAL ERROR: Cannot reach class_cam server or camera hardware.")
    grabber_running = False
    sys.exit()

# --- 6. MAIN LOOP ---
trigger_memory = 0
debug_frame = None

try:
    while True:
        with frame_lock:
            frame = latest_frame
        if frame is None:
            time.sleep(0.01)
            continue

        frame = cv2.flip(frame, 1)

        if plc_connected:
            try:
                trigger_bits = plc.batchread_bitunits(headdevice="B700", readsize=1)
                print(f"B700={trigger_bits}", end="\r")
                if trigger_bits:
                    B700_state = trigger_bits[0]

                    # Rising edge: 0 -> 1
                    if B700_state == 1 and trigger_memory == 0:
                        print("\n>>> PLC TRIGGER (B700) <<<")

                        # --- PRE-PROCESSING ---
                        h, w, _ = frame.shape
                        size = min(h, w)
                        x, y = (w - size) // 2, (h - size) // 2
                        square = frame[y:y+size, x:x+size]

                        rgb = cv2.cvtColor(square, cv2.COLOR_BGR2RGB)
                        img_224 = cv2.resize(rgb, (224, 224), interpolation=cv2.INTER_AREA)
                        c = (224 - 112) // 2  # 56 — center crop to 112x112 then scale back
                        img_input = cv2.resize(img_224[c:c+112, c:c+112], (224, 224), interpolation=cv2.INTER_AREA)
                        img_ready = np.expand_dims(img_input, axis=0).astype(np.float32)
                        # TFLite model has preprocessing baked in — pass raw [0, 255]

                        # Inference
                        interpreter.set_tensor(input_details[0]['index'], img_ready)
                        interpreter.invoke()
                        prediction = interpreter.get_tensor(output_details[0]['index'])[0]

                        idx = np.argmax(prediction)
                        conf = prediction[idx]
                        label = class_names[idx]

                        # Result mapping: 1=pass, 2=fail, 0=null
                        res_val = 0
                        if conf > CONFIDENCE_THRESHOLD:
                            if "pass" in label:
                                res_val = 1
                            elif "fail" in label:
                                res_val = 2

                        result = label.upper() if conf > CONFIDENCE_THRESHOLD else "NULL"
                        print(f"{result} | {int(conf*100)}% -> D8={res_val}")

                        plc.batchwrite_wordunits(headdevice="D8", values=[res_val])

                        # B701=pass, B702=fail, B703=null (one-hot)
                        if res_val == 1:    # pass
                            plc.batchwrite_bitunits(headdevice="B701", values=[1, 0, 0])
                        elif res_val == 2:  # fail
                            plc.batchwrite_bitunits(headdevice="B701", values=[0, 1, 0])
                        else:              # null
                            plc.batchwrite_bitunits(headdevice="B701", values=[0, 0, 1])

                        print(f"B701/702/703 written for res_val={res_val}")

                        plc.batchwrite_bitunits(headdevice="B700", values=[0])

                        save_snapshot_and_log(img_input, label, conf, res_val)

                        debug_frame = cv2.cvtColor(img_input, cv2.COLOR_RGB2BGR)

                    trigger_memory = B700_state

            except Exception as e:
                log.error(f"PLC disconnected: {e}\n{traceback.format_exc()}")
                plc_connected = False
                connect_plc()
        else:
            # No PLC: run inference continuously for debugging
            h, w, _ = frame.shape
            size = min(h, w)
            x, y = (w - size) // 2, (h - size) // 2
            square = frame[y:y+size, x:x+size]

            rgb = cv2.cvtColor(square, cv2.COLOR_BGR2RGB)
            img_224 = cv2.resize(rgb, (224, 224), interpolation=cv2.INTER_AREA)
            c = (224 - 112) // 2  # 56 — center crop to 112x112 then scale back
            img_input = cv2.resize(img_224[c:c+112, c:c+112], (224, 224), interpolation=cv2.INTER_AREA)
            img_ready = np.expand_dims(img_input, axis=0).astype(np.float32)
            # TFLite model has preprocessing baked in — pass raw [0, 255]

            interpreter.set_tensor(input_details[0]['index'], img_ready)
            interpreter.invoke()
            prediction = interpreter.get_tensor(output_details[0]['index'])[0]

            idx = np.argmax(prediction)
            conf = prediction[idx]
            label = class_names[idx]

            debug_frame = cv2.cvtColor(img_input, cv2.COLOR_RGB2BGR)

        # Debug preview — updated every loop, frozen on last triggered frame when PLC connected
        if debug_frame is not None:
            cv2.imshow("AI Input (112x112 center crop @ 224x224)", debug_frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

finally:
    print("\nExiting and Cleaning Up...")
    grabber_running = False
    if plc_connected:
        try:
            plc.batchwrite_wordunits(headdevice="D8", values=[0])
        except: pass
        plc.close()
    cv2.destroyAllWindows()
    if cap is not None:
        cap.release()