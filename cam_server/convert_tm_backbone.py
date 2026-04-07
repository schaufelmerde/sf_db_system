"""
Downloads and converts the Teachable Machine MobileNetV2 backbone
(alpha=0.35, 224x224, no top) from TF.js format to a Keras SavedModel.

Does NOT require the tensorflowjs Python package — parses the TF.js
layers-model format (model.json + binary shards) with pure Python/numpy.

Run once:
    python convert_tm_backbone.py

Produces:  models/tm_backbone/  (Keras SavedModel, includes GAP)
"""

import json
import pathlib
import urllib.request
import numpy as np
import tensorflow as tf
import tf_keras                        # Keras 2 compat layer — handles old TF.js topology format
from tensorflow.keras import layers

# ── Config ───────────────────────────────────────────────────────────────────
BASE_URL = (
    "https://storage.googleapis.com/teachable-machine-models/"
    "mobilenet_v2_weights_tf_dim_ordering_tf_kernels_0.35_224_no_top"
)
DOWNLOAD_DIR = pathlib.Path("models/tm_backbone_tfjs")
OUT_DIR      = pathlib.Path("models/tm_backbone")

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Step 1 – download model.json and weight shards ───────────────────────────
def download(url, dest: pathlib.Path):
    if dest.exists():
        print(f"  cached  : {dest.name}")
        return
    print(f"  fetching: {dest.name}  ← {url}")
    urllib.request.urlretrieve(url, dest)

print("Downloading TF.js model files...")
model_json_path = DOWNLOAD_DIR / "model.json"
download(f"{BASE_URL}/model.json", model_json_path)

with open(model_json_path, encoding="utf-8") as f:
    model_json = json.load(f)

weight_manifest = model_json["weightsManifest"]
for group in weight_manifest:
    for shard in group["paths"]:
        download(f"{BASE_URL}/{shard}", DOWNLOAD_DIR / shard)

# ── Step 2 – parse binary shards into numpy arrays ───────────────────────────
print("\nParsing weight shards...")

DTYPE_MAP = {
    "float32": (np.float32, 4),
    "int32":   (np.int32,   4),
    "bool":    (np.bool_,   1),
}

# Concatenate all shard bytes in manifest order
raw_bytes = b""
all_specs = []
for group in weight_manifest:
    shard_bytes = b""
    for shard in group["paths"]:
        with open(DOWNLOAD_DIR / shard, "rb") as f:
            shard_bytes += f.read()
    # weights within a group are laid out sequentially in the group's shards
    offset = 0
    for spec in group["weights"]:
        dtype_np, item_size = DTYPE_MAP[spec.get("dtype", "float32")]
        shape = spec["shape"]
        n_elem = int(np.prod(shape)) if shape else 1
        n_bytes = n_elem * item_size
        arr = np.frombuffer(shard_bytes[offset: offset + n_bytes], dtype=dtype_np)
        arr = arr.reshape(shape) if shape else arr.reshape(())
        all_specs.append((spec["name"], arr))
        offset += n_bytes

weights_by_name = dict(all_specs)
print(f"  Parsed {len(weights_by_name)} tensors")

# ── Step 3 – recreate the Keras model from modelTopology ─────────────────────
print("\nRebuilding Keras model from modelTopology...")

topology = model_json["modelTopology"]
# TF.js layers-model topology wraps the config under "model_config"
model_config_json = json.dumps(
    topology.get("model_config", topology)
)
backbone_raw = tf_keras.models.model_from_json(model_config_json)
print(f"  Model class : {backbone_raw.__class__.__name__}")
print(f"  Output shape: {backbone_raw.output_shape}")

# ── Step 4 – load weights by name ────────────────────────────────────────────
print("\nLoading weights...")
missing, loaded = [], 0

for var in backbone_raw.weights:
    # Keras name:  "mobilenetv2_0.35_224/conv1_bn/gamma:0"
    # TF.js name:  "mobilenetv2_0.35_224/conv1_bn/gamma"
    tfjs_name = var.name.split(":")[0]

    if tfjs_name in weights_by_name:
        arr = weights_by_name[tfjs_name]
        if arr.shape != tuple(var.shape):
            raise ValueError(
                f"Shape mismatch for {tfjs_name}: "
                f"Keras {tuple(var.shape)} vs TF.js {arr.shape}"
            )
        var.assign(arr)
        loaded += 1
    else:
        missing.append(tfjs_name)

print(f"  Loaded : {loaded}")
if missing:
    print(f"  Missing: {len(missing)}")
    for n in missing[:10]:
        print(f"    {n}")
    if len(missing) > 10:
        print(f"    ... and {len(missing)-10} more")

backbone_raw.trainable = False

# ── Step 5 – transfer weights to a fresh tf.keras (Keras 3) MobileNetV2 ─────
# tf_keras (Keras 2) models can't be saved in a format Keras 3 can load.
# Both models are identical MobileNetV2 architectures, so weights are in the
# same order — we just copy them by position.
print("\nTransferring weights to Keras 3 MobileNetV2...")

keras3_base = tf.keras.applications.MobileNetV2(
    input_shape=(224, 224, 3),
    include_top=False,
    weights=None,       # don't load ImageNet weights — we'll set TM weights
    alpha=0.35
)

tfk2_weights = backbone_raw.get_weights()
k3_weights   = keras3_base.get_weights()

if len(tfk2_weights) != len(k3_weights):
    raise ValueError(
        f"Weight count mismatch: tf_keras={len(tfk2_weights)}, "
        f"tf.keras={len(k3_weights)}"
    )

for i, (w2, w3) in enumerate(zip(tfk2_weights, k3_weights)):
    if w2.shape != w3.shape:
        raise ValueError(
            f"Shape mismatch at position {i}: "
            f"tf_keras {w2.shape} vs tf.keras {w3.shape}"
        )

keras3_base.set_weights(tfk2_weights)
keras3_base.trainable = False
print(f"  Transferred {len(tfk2_weights)} weight tensors")

# ── Step 6 – attach GlobalAveragePooling2D (mirrors TM's truncated model) ────
inp = tf.keras.Input(shape=(224, 224, 3))
x   = keras3_base(inp, training=False)
x   = tf.keras.layers.GlobalAveragePooling2D()(x)
tm_backbone = tf.keras.Model(inp, x, name="tm_backbone")
tm_backbone.trainable = False
print(f"  Final backbone output shape: {tm_backbone.output_shape}")  # (None, 1280)

# ── Step 7 – sanity check ────────────────────────────────────────────────────
dummy = tf.zeros((1, 224, 224, 3))
out   = tm_backbone(dummy, training=False)
assert tf.reduce_all(tf.math.is_finite(out)).numpy(), "Output has NaN/Inf!"
print("  Sanity check passed (output is finite).")

# ── Step 8 – save as native Keras 3 .keras file ──────────────────────────────
keras_path = str(OUT_DIR) + ".keras"
tm_backbone.save(keras_path)
print(f"\nSaved TM backbone to: {keras_path}")
print("Now run train.py - it will pick this backbone up automatically.")
