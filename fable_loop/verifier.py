"""Verify a cycle's output before promoting it to the next cycle's input."""
import os

import cv2

from analyzer.video_analyzer import get_video_info


def _verify_image(output_file):
    img = cv2.imread(output_file)
    if img is None or img.size == 0:
        return False, 'Image failed to decode (corrupted output)', None
    return True, 'ok', {'shape': list(img.shape)}


def _verify_video(output_file):
    info = get_video_info(output_file)
    streams = info.get('streams', [])
    if not any(s.get('codec_type') == 'video' for s in streams):
        return False, 'ffprobe found no video stream (corrupted or invalid output)', None

    try:
        duration = float(info.get('format', {}).get('duration', 0))
    except (TypeError, ValueError):
        duration = 0.0

    if duration <= 0:
        return False, 'ffprobe reported zero/invalid duration (corrupted output)', None

    return True, 'ok', {'duration': duration}


def verify_output(output_file, is_image):
    """Check a cycle's output file exists, isn't corrupted, and (for video) has a
    valid duration. Deliberately doesn't compare against the previous file's
    duration: trimming (a supported edit type) legitimately produces much
    shorter output, so a shorter-than-input heuristic would false-flag valid
    edits as corrupted. Returns (ok, reason, info)."""
    if not output_file or not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
        return False, 'Output file missing or empty', None

    if is_image:
        return _verify_image(output_file)
    return _verify_video(output_file)
