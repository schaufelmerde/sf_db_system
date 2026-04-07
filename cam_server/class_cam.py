import cv2
import os
import json
import threading
import numpy as np
from flask import Flask, Response, request

os.environ["OPENCV_VIDEOIO_PRIORITY_MSMF"] = "0"  # Force DirectShow, MSMF broken on new opencv

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

app = Flask(__name__)
camera_lock = threading.Lock()
camera_active = True

def _open_camera():
    for index in range(4):
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if cap.isOpened():
            ok, _ = cap.read()
            if ok:
                log.info(f"Camera opened on index {index}")
                return cap
            cap.release()
        log.warning(f"Camera index {index} not available")
    log.error("No camera found on indices 0-3")
    return None

camera = _open_camera()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- TFLite interpreter ---
try:
    from ai_edge_litert.interpreter import Interpreter as TFLiteInterpreter
except ImportError:
    try:
        from tflite_runtime.interpreter import Interpreter as TFLiteInterpreter
    except ImportError:
        from tensorflow.lite.python.interpreter import Interpreter as TFLiteInterpreter

# --- Model cache ---
_model_lock = threading.Lock()
_cached_model_path = None
_cached_interpreter = None
_cached_labels = None


def _load_model(model_dir):
    global _cached_model_path, _cached_interpreter, _cached_labels
    model_path = os.path.join(model_dir, "model_unquant.tflite")
    labels_path = os.path.join(model_dir, "labels.txt")
    with _model_lock:
        if _cached_model_path != model_path:
            interp = TFLiteInterpreter(model_path=model_path)
            interp.allocate_tensors()
            with open(labels_path, "r") as f:
                labels = [line.strip().split(" ", 1)[-1].lower() for line in f]
            _cached_interpreter = interp
            _cached_labels = labels
            _cached_model_path = model_path
        return _cached_interpreter, _cached_labels


# --- Routes ---

@app.route('/')
@app.route('/monitor')
def monitor():
    return """
    <html>
      <head>
        <meta http-equiv="X-UA-Compatible" content="IE=edge">
        <style>
          body { margin:0; background:#000; overflow:hidden; font-family:monospace; }
          #overlay {
            display:none; position:absolute; inset:0;
            align-items:center; justify-content:center; flex-direction:column;
            color:#f87171; font-size:14px; gap:8px;
          }
          #overlay.visible { display:flex; }
          #dot { width:8px; height:8px; border-radius:50%; background:#4ade80;
                 position:absolute; top:10px; right:10px; }
          #dot.error { background:#f87171; }
        </style>
        <script>
          var failCount = 0;
          function updateImage() {
            var img = document.getElementById('cameraGui');
            var overlay = document.getElementById('overlay');
            var dot = document.getElementById('dot');
            var newImg = new Image();
            newImg.onload = function() {
                img.src = this.src;
                overlay.classList.remove('visible');
                dot.classList.remove('error');
                failCount = 0;
                setTimeout(updateImage, 30);
            };
            newImg.onerror = function() {
                failCount++;
                if (failCount > 5) {
                    overlay.classList.add('visible');
                    dot.classList.add('error');
                    fetch('/api/camera/status').then(r=>r.json()).then(d=>{
                        document.getElementById('errmsg').textContent =
                            d.error || (d.active ? 'Camera read failed' : 'Camera is off');
                    }).catch(()=>{});
                }
                setTimeout(updateImage, 500);
            };
            newImg.src = "/single_frame?t=" + new Date().getTime();
          }
          window.onload = updateImage;
        </script>
      </head>
      <body>
        <div id="dot"></div>
        <img id="cameraGui" style="width:100%;height:100%;object-fit:contain;">
        <div id="overlay">
          <span style="font-size:32px;">&#9888;</span>
          <span id="errmsg">No camera signal</span>
          <span style="color:#64748b;font-size:11px;">Check camera connection and restart the server</span>
        </div>
      </body>
    </html>
    """


@app.route('/api/camera/toggle', methods=['POST'])
def camera_toggle():
    global camera_active
    camera_active = not camera_active
    return Response(json.dumps({"active": camera_active}), mimetype='application/json')

@app.route('/api/camera/status')
def camera_status():
    payload = {"active": camera_active, "available": camera is not None}
    if camera is None:
        payload["error"] = "No camera found on indices 0-3"
    return Response(json.dumps(payload), mimetype='application/json')

@app.route('/single_frame')
def single_frame():
    if not camera_active:
        return Response(json.dumps({"error": "camera off"}), status=503, mimetype='application/json')
    if camera is None:
        return Response(json.dumps({"error": "no camera"}), status=503, mimetype='application/json')
    with camera_lock:
        success, frame = camera.read()
    if not success:
        return Response(json.dumps({"error": "camera read failed"}), status=500, mimetype='application/json')
    # Mirror classifier.py preprocessing exactly
    frame = cv2.flip(frame, 1)
    h, w = frame.shape[:2]
    size = min(h, w)
    x, y = (w - size) // 2, (h - size) // 2
    square = frame[y:y + size, x:x + size]
    rgb = cv2.cvtColor(square, cv2.COLOR_BGR2RGB)
    img_224 = cv2.resize(rgb, (224, 224), interpolation=cv2.INTER_AREA)
    c = (224 - 112) // 2
    img_input = cv2.resize(img_224[c:c+112, c:c+112], (224, 224), interpolation=cv2.INTER_AREA)
    preview_bgr = cv2.cvtColor(img_input, cv2.COLOR_RGB2BGR)
    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 85]
    ret, buffer = cv2.imencode('.jpg', preview_bgr, encode_param)
    return Response(buffer.tobytes(), mimetype='image/jpeg')


@app.route('/raw_frame')
def raw_frame():
    """Square-crop + resize to 224×224 only — no zoom crop, no normalization.
    Used by classifier.py so it can apply its own preprocessing without double-processing."""
    if not camera_active:
        return Response(json.dumps({"error": "camera off"}), status=503, mimetype='application/json')
    if camera is None:
        return Response(json.dumps({"error": "no camera"}), status=503, mimetype='application/json')
    with camera_lock:
        success, frame = camera.read()
    if not success:
        return Response(json.dumps({"error": "camera read failed"}), status=500, mimetype='application/json')
    frame = cv2.flip(frame, 1)
    h, w = frame.shape[:2]
    size = min(h, w)
    x, y = (w - size) // 2, (h - size) // 2
    square = frame[y:y + size, x:x + size]
    img_224 = cv2.resize(square, (224, 224), interpolation=cv2.INTER_AREA)
    ret, buffer = cv2.imencode('.jpg', img_224, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    return Response(buffer.tobytes(), mimetype='image/jpeg')


@app.route('/api/models')
def api_models():
    models_dir = os.path.join(BASE_DIR, "models")
    found = []
    for name in sorted(os.listdir(models_dir)):
        if not name.startswith("tflite_"):
            continue
        folder = os.path.join(models_dir, name)
        if (os.path.isdir(folder)
                and os.path.isfile(os.path.join(folder, "model_unquant.tflite"))
                and os.path.isfile(os.path.join(folder, "labels.txt"))):
            found.append(f"models/{name}")
    return Response(json.dumps(found), mimetype='application/json')


@app.route('/api/classify')
def api_classify():
    # MO
    model_rel = request.args.get("model", "models/tflite_90")

    # Prevent path traversal
    model_abs = os.path.abspath(os.path.join(BASE_DIR, model_rel))
    models_root = os.path.abspath(os.path.join(BASE_DIR, "models"))
    if not model_abs.startswith(models_root):
        return Response(json.dumps({"error": "invalid model path"}), status=400,
                        mimetype='application/json')

    if not os.path.isfile(os.path.join(model_abs, "model_unquant.tflite")):
        return Response(json.dumps({"error": "model not found"}), status=404,
                        mimetype='application/json')

    try:
        interp, labels = _load_model(model_abs)
    except Exception as e:
        return Response(json.dumps({"error": str(e)}), status=500,
                        mimetype='application/json')

    if not camera_active:
        return Response(json.dumps({"error": "camera off"}), status=503, mimetype='application/json')
    if camera is None:
        return Response(json.dumps({"error": "no camera"}), status=503, mimetype='application/json')
    with camera_lock:
        success, frame = camera.read()
    if not success:
        return Response(json.dumps({"error": "camera read failed"}), status=500,
                        mimetype='application/json')

    # Preprocess identical to classifier.py
    frame = cv2.flip(frame, 1)
    h, w = frame.shape[:2]
    size = min(h, w)
    x, y = (w - size) // 2, (h - size) // 2
    square = frame[y:y + size, x:x + size]
    rgb = cv2.cvtColor(square, cv2.COLOR_BGR2RGB)
    img_224 = cv2.resize(rgb, (224, 224), interpolation=cv2.INTER_AREA)
    c = (224 - 112) // 2
    img_input = cv2.resize(img_224[c:c+112, c:c+112], (224, 224), interpolation=cv2.INTER_AREA)
    img_ready = np.expand_dims(img_input, axis=0).astype(np.float32)
    # TFLite model has preprocessing baked in (Lambda: x/127 - 1) — pass raw [0, 255]

    with _model_lock:
        input_details = interp.get_input_details()
        output_details = interp.get_output_details()
        interp.set_tensor(input_details[0]["index"], img_ready)
        interp.invoke()
        prediction = interp.get_tensor(output_details[0]["index"])[0]

    scores = sorted(
        [{"name": labels[i], "score": float(prediction[i])} for i in range(len(labels))],
        key=lambda x: x["score"],
        reverse=True
    )
    return Response(json.dumps({"scores": scores}), mimetype='application/json')


def _gen_mjpeg():
    """Yield MJPEG frames for a continuous video stream."""
    import time
    while True:
        if not camera_active or camera is None:
            time.sleep(0.1)
            continue
        with camera_lock:
            success, frame = camera.read()
        if not success:
            time.sleep(0.05)
            continue
        frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]
        size = min(h, w)
        x, y = (w - size) // 2, (h - size) // 2
        square = frame[y:y + size, x:x + size]
        rgb = cv2.cvtColor(square, cv2.COLOR_BGR2RGB)
        img_224 = cv2.resize(rgb, (224, 224), interpolation=cv2.INTER_AREA)
        c = (224 - 112) // 2
        img_input = cv2.resize(img_224[c:c+112, c:c+112], (224, 224), interpolation=cv2.INTER_AREA)
        preview_bgr = cv2.cvtColor(img_input, cv2.COLOR_RGB2BGR)
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
        ret, buffer = cv2.imencode('.jpg', preview_bgr, encode_param)
        if not ret:
            continue
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        time.sleep(1 / 30)


@app.route('/video_feed')
def video_feed():
    return Response(_gen_mjpeg(), mimetype='multipart/x-mixed-replace; boundary=frame')


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, threaded=True)
