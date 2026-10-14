"""Bounded local-only Haar portrait detection; never an identity verifier."""

from pathlib import Path

import cv2
import numpy as np
from cv2 import data
from PIL import Image, ImageOps

from clipfactory.domain.portrait import FaceBox


def detect_portrait_face(path: Path) -> FaceBox | None:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((1600, 1600))
    pixels = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    cascade = cv2.CascadeClassifier(data.haarcascades + "haarcascade_frontalface_default.xml")
    if cascade.empty():
        raise RuntimeError("local portrait face cascade is unavailable")
    try:
        boxes, _, weights = cascade.detectMultiScale3(
            pixels, scaleFactor=1.1, minNeighbors=6, minSize=(40, 40), outputRejectLevels=True
        )
    except cv2.error as exc:
        raise RuntimeError("local portrait face detection failed") from exc
    candidates = sorted(
        (tuple(int(v) for v in box) for box, weight in zip(boxes, weights, strict=True) if float(weight) >= 5),
        key=lambda box: (-box[2] * box[3], box[0], box[1]),
    )
    # Do not guess the subject in a group photo: require a clearly dominant face.
    if not candidates or (
        len(candidates) > 1 and candidates[0][2] * candidates[0][3] < 2 * candidates[1][2] * candidates[1][3]
    ):
        return None
    x, y, width, height = candidates[0]
    return FaceBox(x / image.width, y / image.height, width / image.width, height / image.height)
