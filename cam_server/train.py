import os
import re
import math
import argparse
import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, models

# ── CLI args ────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument('--epochs',      type=int,   default=50)
parser.add_argument('--lr',          type=float, default=0.001)
parser.add_argument('--batch-size',  type=int,   default=16)
parser.add_argument('--dense-units', type=int,   default=128)
parser.add_argument('--alpha',       type=float, default=0.35)
parser.add_argument('--val-split',   type=float, default=0.15)
parser.add_argument('--augment',     action='store_true')
parser.add_argument('--optimizer',   type=str,   default='adam', choices=['adam', 'sgd', 'rmsprop', 'adagrad'])
parser.add_argument('--momentum',    type=float, default=0.9,   help='Momentum for SGD/RMSprop')
parser.add_argument('--aug-intensity', type=float, default=1.0, help='Scales augmentation magnitude')
args = parser.parse_args()

# ── Paths ──────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(BASE_DIR, "image_dataset")
MODELS_DIR  = os.path.join(BASE_DIR, "models")
TM_BACKBONE = os.path.join(MODELS_DIR, "tm_backbone.keras")

# ── Auto-detect next tflite_N slot ─────────────────────────────────────
os.makedirs(MODELS_DIR, exist_ok=True)
existing = [int(m.group(1)) for name in os.listdir(MODELS_DIR) if (m := re.fullmatch(r"tflite_(\d+)", name))]
next_n   = max(existing) + 1 if existing else 1
OUT_DIR  = os.path.join(MODELS_DIR, f"tflite_{next_n}")
os.makedirs(OUT_DIR, exist_ok=True)

# ── Settings ────────────────────────────────────────────────────────────
IMG_SIZE    = (224, 224)
BATCH_SIZE  = args.batch_size
EPOCHS      = args.epochs
LEARN_RATE  = args.lr
DENSE_UNITS = args.dense_units
VAL_SPLIT   = args.val_split
CLASS_ORDER = ["pass", "fail", "null"]

# ── Build Feature Extractor ──────────────────────────────────────────────
print("\nBuilding feature extractor...")

def preprocess(x):
    return tf.cast(x, tf.float32) / 127.0 - 1.0

if os.path.isfile(TM_BACKBONE):
    print("  Using converted TM backbone")
    backbone = tf.keras.models.load_model(TM_BACKBONE)
    backbone.trainable = False
    
    feature_extractor = models.Sequential([
        layers.Input(shape=(*IMG_SIZE, 3)),
        layers.Lambda(preprocess),
        backbone,
    ], name="feature_extractor")
else:
    print(f"  Using standard MobileNetV2 Alpha={args.alpha}")
    backbone = tf.keras.applications.MobileNetV2(
        input_shape=(*IMG_SIZE, 3),
        include_top=False,
        weights="imagenet",
        alpha=args.alpha
    )
    backbone.trainable = False

    feature_extractor = models.Sequential([
        layers.Input(shape=(*IMG_SIZE, 3)),
        layers.Lambda(preprocess),
        backbone,
        layers.GlobalAveragePooling2D(),
    ], name="feature_extractor")

# ── Load & Pre-extract Features ─────────────────────────────────────────
print("\nExtracting features from dataset...")
raw_ds = tf.keras.utils.image_dataset_from_directory(
    DATASET_DIR,
    image_size=IMG_SIZE,
    batch_size=BATCH_SIZE,
    class_names=CLASS_ORDER,
    label_mode="categorical",
    shuffle=False
)

all_features, all_labels, all_images = [], [], []
for images, labels in raw_ds:
    feats = feature_extractor(images, training=False)
    all_features.append(feats.numpy())
    all_labels.append(labels.numpy())
    if args.augment:
        all_images.append(images.numpy())

all_features = np.concatenate(all_features, axis=0)
all_labels   = np.concatenate(all_labels,   axis=0)
X_train_raw = np.concatenate(all_images, axis=0) if args.augment else None

# ── Per-class Split ─────────────────────────────────────────────────────
train_idx, val_idx = [], []
for c in range(len(CLASS_ORDER)):
    idx = np.where(all_labels[:, c] == 1)[0]
    np.random.shuffle(idx)
    cut = max(1, math.ceil(len(idx) * VAL_SPLIT))
    val_idx.extend(idx[:cut])
    train_idx.extend(idx[cut:])

X_train, y_train = all_features[train_idx], all_labels[train_idx]
X_val,   y_val   = all_features[val_idx],   all_labels[val_idx]

# ── Augmentation ────────────────────────────────────────────────────────
if args.augment:
    print(f"\nAugmenting training samples (Intensity: {args.aug_intensity})")
    aug_fn = tf.keras.Sequential([
        layers.RandomFlip("horizontal"),
        layers.RandomRotation(0.1 * args.aug_intensity),
        layers.RandomZoom(0.1 * args.aug_intensity),
        layers.RandomBrightness(min(0.15 * args.aug_intensity, 0.5)),
    ])
    
    aug_feats, aug_lbls = [X_train], [y_train]
    train_imgs_subset = tf.constant(X_train_raw[train_idx])
    
    for _ in range(2): 
        batched = []
        for i in range(0, len(train_imgs_subset), BATCH_SIZE):
            a_batch = aug_fn(train_imgs_subset[i:i + BATCH_SIZE], training=True)
            batched.append(feature_extractor(a_batch, training=False).numpy())
        aug_feats.append(np.concatenate(batched, axis=0))
        aug_lbls.append(y_train)
    
    X_train = np.concatenate(aug_feats, axis=0)
    y_train = np.concatenate(aug_lbls,  axis=0)

# ── Build & Train Head (Robust Version) ─────────────────────────────────
initializer = tf.keras.initializers.VarianceScaling(scale=1.0, mode='fan_in', distribution='truncated_normal')

head = models.Sequential([
    layers.Input(shape=(all_features.shape[1],)),
    layers.Dense(DENSE_UNITS, activation="relu", kernel_initializer=initializer),
    layers.Dense(len(CLASS_ORDER), activation="softmax", kernel_initializer=initializer, use_bias=False),
], name="tm_head")

_optims = {
    'adam':    lambda: tf.keras.optimizers.Adam(learning_rate=LEARN_RATE),
    'sgd':     lambda: tf.keras.optimizers.SGD(learning_rate=LEARN_RATE, momentum=args.momentum),
    'rmsprop': lambda: tf.keras.optimizers.RMSprop(learning_rate=LEARN_RATE, momentum=args.momentum),
}

# Label smoothing of 0.1 prevents the model from being 100% sure, improving generalization
head.compile(
    optimizer=_optims.get(args.optimizer, _optims['adam'])(),
    loss='categorical_crossentropy', 
    metrics=["accuracy"]
)

print("\nTraining Head...")
head.fit(X_train, y_train, validation_data=(X_val, y_val), 
         epochs=EPOCHS, batch_size=BATCH_SIZE, verbose=1)

# ── Export ──────────────────────────────────────────────────────────────
full_model = models.Sequential([feature_extractor, head])
converter = tf.lite.TFLiteConverter.from_keras_model(full_model)
with open(os.path.join(OUT_DIR, "model_unquant.tflite"), "wb") as f:
    f.write(converter.convert())

with open(os.path.join(OUT_DIR, "labels.txt"), "w") as f:
    for i, name in enumerate(CLASS_ORDER):
        f.write(f"{i} {name}\n")

print(f"\nSuccess! Exported to {OUT_DIR}")