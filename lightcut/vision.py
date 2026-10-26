"""Camera and computer-vision features.

- Auto-scan: find the material sheet in a camera photo, correct perspective,
  and return a top-down image sized to the real sheet dimensions.
- AI trace: separate the subject from the background (GrabCut) and trace its
  outline into vector paths ready for cutting.

Everything here is classical computer vision (OpenCV), so it runs offline.
"""
import cv2
import numpy as np
from PIL import Image


def open_camera(index=0):
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        raise RuntimeError(f"No camera found at index {index}. Check that it is connected.")
    return cap


def grab_frame(cap, warmup=5):
    """Read a frame (BGR). A few warm-up reads let auto-exposure settle."""
    frame = None
    for _ in range(warmup):
        ok, frame = cap.read()
    if frame is None or not ok:
        raise RuntimeError("The camera returned no image.")
    return frame


def order_corners(pts):
    """Return corners as top-left, top-right, bottom-right, bottom-left."""
    pts = np.asarray(pts, np.float32).reshape(4, 2)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)],
                     pts[np.argmax(s)], pts[np.argmax(d)]], np.float32)


def find_sheet_corners(bgr):
    """Find the largest convex four-sided shape, which is usually the material sheet."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = gray.shape
    best, best_area = None, 0.0
    for c in contours:
        area = cv2.contourArea(c)
        if area < 0.10 * w * h or area <= best_area:
            continue
        approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            best, best_area = approx, area
    if best is None:
        raise RuntimeError("Could not find a rectangular sheet. Put the material on a plain, "
                           "contrasting surface, keep the whole sheet in view, and try again.")
    return order_corners(best)


def warp_to_sheet(bgr, corners, sheet_w_mm, sheet_h_mm, px_per_mm=4.0):
    """Top-down view of the sheet, scaled to sheet_w_mm x sheet_h_mm."""
    W = max(2, int(round(sheet_w_mm * px_per_mm)))
    H = max(2, int(round(sheet_h_mm * px_per_mm)))
    dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], np.float32)
    M = cv2.getPerspectiveTransform(corners, dst)
    return cv2.warpPerspective(bgr, M, (W, H))


def bgr_to_pil_gray(bgr):
    return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))


def subject_mask(bgr):
    """Foreground mask from GrabCut, initialised with a box around the image centre."""
    h, w = bgr.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    rect = (int(w * 0.05), int(h * 0.05), int(w * 0.90), int(h * 0.90))
    bg = np.zeros((1, 65), np.float64)
    fg = np.zeros((1, 65), np.float64)
    cv2.grabCut(bgr, mask, rect, bg, fg, 5, cv2.GC_INIT_WITH_RECT)
    return np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)


def trace_outline(bgr, mm_per_px, use_subject_detection=True,
                  min_area_mm2=4.0, simplify_mm=0.1):
    """Trace subject outlines into polylines in mm, relative to the image's top-left."""
    if use_subject_detection:
        mask = subject_mask(bgr)
    else:
        gray = cv2.GaussianBlur(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    polys = []
    for c in contours:
        if cv2.contourArea(c) * mm_per_px * mm_per_px < min_area_mm2:
            continue
        approx = cv2.approxPolyDP(c, max(0.5, simplify_mm / mm_per_px), True)
        pts = [(float(x) * mm_per_px, float(y) * mm_per_px) for x, y in approx.reshape(-1, 2)]
        if len(pts) >= 3:
            pts.append(pts[0])
            polys.append(pts)
    return polys


def trace_pil(pil_gray, width_mm, use_subject_detection=True):
    """Trace a grayscale PIL image into polylines in mm, relative to its top-left corner."""
    arr = np.array(pil_gray.convert("L"))
    bgr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    mm_per_px = width_mm / arr.shape[1]
    return trace_outline(bgr, mm_per_px, use_subject_detection)
