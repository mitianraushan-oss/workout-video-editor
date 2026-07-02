"""Video analysis: brightness, motion segments, rep estimation (OpenCV)."""
import json
import subprocess
from datetime import timedelta

import cv2
import numpy as np


def format_time(seconds):
    return str(timedelta(seconds=int(seconds)))[2:7]


def get_video_info(video_path):
    """Get video metadata using ffprobe"""
    cmd = [
        'ffprobe', '-v', 'error', '-print_format', 'json',
        '-show_format', '-show_streams', video_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {}


def analyze_video(video_path, task_id, processing_status):
    """Analyze video and update status"""
    try:
        processing_status[task_id]['status'] = 'analyzing'

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            processing_status[task_id]['status'] = 'error'
            processing_status[task_id]['error'] = 'Cannot open video'
            return

        # Basic info
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        duration = frame_count / fps if fps > 0 else 0

        analysis = {
            'duration': round(duration, 2),
            'fps': round(fps, 2),
            'resolution': {'width': width, 'height': height},
            'frame_count': frame_count,
            'brightness': 0,
            'motion_segments': [],
            'quiet_segments': [],
            'has_audio': False,
            'estimated_reps': 0,
            'suggestions': []
        }

        # Check audio
        probe = get_video_info(video_path)
        streams = probe.get('streams', [])
        analysis['has_audio'] = any(s.get('codec_type') == 'audio' for s in streams)

        # Brightness analysis
        brightness_values = []
        motion_data = []
        total_frames = min(frame_count, 300)  # Sample max 300 frames for speed
        step = max(1, frame_count // total_frames) if total_frames > 0 else 1

        ret, prev_frame = cap.read()
        if ret:
            prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
            prev_gray = cv2.GaussianBlur(prev_gray, (21, 21), 0)
            brightness_values.append(np.mean(prev_gray))

            frame_num = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                frame_num += 1
                if frame_num % step != 0:
                    continue

                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray_blur = cv2.GaussianBlur(gray, (21, 21), 0)

                # Brightness
                brightness_values.append(np.mean(gray))

                # Motion
                diff = cv2.absdiff(prev_gray, gray_blur)
                _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
                motion_score = np.sum(thresh) / 255

                motion_data.append({
                    'frame': frame_num,
                    'time': frame_num / fps,
                    'motion': float(motion_score)
                })

                prev_gray = gray_blur

                # Update progress
                progress = min(90, (frame_num / frame_count) * 100)
                processing_status[task_id]['progress'] = progress

            analysis['brightness'] = round(np.mean(brightness_values), 2)

        cap.release()

        # Find motion segments
        segments = []
        current_segment = None
        min_motion = 300

        for md in motion_data:
            if md['motion'] > min_motion:
                if current_segment is None:
                    current_segment = {
                        'start_time': md['time'],
                        'start_frame': md['frame'],
                        'max_motion': md['motion']
                    }
                else:
                    current_segment['max_motion'] = max(
                        current_segment['max_motion'], md['motion']
                    )
            else:
                if current_segment is not None:
                    current_segment['end_time'] = md['time']
                    current_segment['end_frame'] = md['frame']
                    current_segment['duration'] = round(
                        current_segment['end_time'] - current_segment['start_time'], 2
                    )
                    if current_segment['duration'] > 0.5:
                        segments.append(current_segment)
                    current_segment = None

        analysis['motion_segments'] = segments

        # Estimate reps
        total_reps = 0
        for seg in segments:
            if seg['duration'] > 1:
                reps = max(1, int(seg['duration'] / 2.5))
                seg['estimated_reps'] = reps
                total_reps += reps
        analysis['estimated_reps'] = total_reps

        # Find quiet segments
        if segments:
            quiet = []
            prev_end = 0
            for seg in segments:
                if seg['start_time'] - prev_end > 1:
                    quiet.append({
                        'start_time': prev_end,
                        'end_time': seg['start_time'],
                        'duration': round(seg['start_time'] - prev_end, 2)
                    })
                prev_end = seg['end_time']
            if duration - prev_end > 1:
                quiet.append({
                    'start_time': prev_end,
                    'end_time': duration,
                    'duration': round(duration - prev_end, 2)
                })
            analysis['quiet_segments'] = quiet

        # Generate suggestions
        if analysis['brightness'] < 80:
            analysis['suggestions'].append({
                'type': 'brightness',
                'icon': '☀️',
                'title': 'Low Brightness',
                'description': 'Video appears dark',
                'fix': 'Increase brightness by 20-30%'
            })
        elif analysis['brightness'] > 200:
            analysis['suggestions'].append({
                'type': 'brightness',
                'icon': '🔆',
                'title': 'Overexposed',
                'description': 'Video is too bright',
                'fix': 'Decrease brightness'
            })

        for q in analysis['quiet_segments']:
            if q['duration'] > 3:
                analysis['suggestions'].append({
                    'type': 'trim',
                    'icon': '✂️',
                    'title': 'Quiet Section',
                    'description': f'{q["duration"]}s of low activity at {format_time(q["start_time"])}',
                    'fix': 'Trim or speed up this section'
                })

        for seg in segments[:5]:
            if seg['max_motion'] > 1500:
                analysis['suggestions'].append({
                    'type': 'slowmo',
                    'icon': '🐢',
                    'title': 'Peak Movement',
                    'description': f'Intense motion at {format_time(seg["start_time"])}',
                    'fix': 'Add slow-motion effect'
                })

        if not analysis['has_audio']:
            analysis['suggestions'].append({
                'type': 'music',
                'icon': '🎵',
                'title': 'No Audio',
                'description': 'No audio track detected',
                'fix': 'Add background music'
            })

        processing_status[task_id]['analysis'] = analysis
        processing_status[task_id]['status'] = 'analyzed'
        processing_status[task_id]['progress'] = 100

    except Exception as e:
        processing_status[task_id]['status'] = 'error'
        processing_status[task_id]['error'] = str(e)
