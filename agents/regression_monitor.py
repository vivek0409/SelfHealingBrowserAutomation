import os
from PIL import Image, ImageChops
from datetime import datetime

def compare_screenshots(
    baseline_path: str,
    current_path: str,
    output_diff_dir: str,
    threshold: float = 0.5
) -> dict:
    """
    Compares baseline and current screenshots using Pillow.
    Returns a dict with diff_percentage, status, and diff_image_path (if diff found).
    """
    if not os.path.exists(baseline_path):
        raise FileNotFoundError(f"Baseline screenshot not found at: {baseline_path}")
    if not os.path.exists(current_path):
        raise FileNotFoundError(f"Current screenshot not found at: {current_path}")
        
    os.makedirs(output_diff_dir, exist_ok=True)
    diff_image_path = os.path.join(output_diff_dir, "visual_diff.png")
    
    img1 = Image.open(baseline_path).convert("RGB")
    img2 = Image.open(current_path).convert("RGB")

    # If sizes differ, resize current image to match baseline
    if img1.size != img2.size:
        img2 = img2.resize(img1.size, Image.Resampling.LANCZOS)

    width, height = img1.size
    total_pixels = width * height

    # Per-pixel absolute difference, collapsed to a single-channel "max change" map.
    # Doing this with Pillow primitives keeps it vectorized in C instead of a slow
    # per-pixel Python loop (which stalled on full-page screenshots).
    diff = ImageChops.difference(img1, img2)
    diff_gray = diff.convert("L")  # luminance approximates the magnitude of change

    # Build a binary mask: pixels whose change exceeds the noise threshold (>10).
    NOISE_THRESHOLD = 10
    mask = diff_gray.point(lambda v: 255 if v > NOISE_THRESHOLD else 0).convert("L")

    # Count changed pixels from the mask histogram (index 255 holds the white count).
    non_zero_pixels = mask.histogram()[255]
    diff_percentage = (non_zero_pixels / total_pixels) * 100 if total_pixels else 0.0

    status = "pass"
    if diff_percentage > threshold:
        status = "fail"

    # Composite a solid-red layer onto the baseline wherever the mask is set, so the
    # saved diff image highlights exactly what changed.
    red_layer = Image.new("RGB", img1.size, (255, 0, 0))
    highlight_img = Image.composite(red_layer, img1, mask)

    # Save the highlighted diff image
    highlight_img.save(diff_image_path)
    
    return {
        "diff_percentage": round(diff_percentage, 2),
        "status": status,
        "diff_image_path": diff_image_path if diff_percentage > 0 else None,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
