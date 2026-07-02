"""Image analysis for workout photos."""
import cv2
import numpy as np


class WorkoutImageAnalyzer:
    """Analyzes a single workout image and produces the same analysis shape
    the frontend renders for videos (segments/reps stay empty)."""

    def __init__(self, image_path):
        self.image_path = image_path
        self.analysis = None

    def analyze(self):
        img = cv2.imread(self.image_path)
        if img is None:
            raise ValueError('Cannot open image')

        height, width = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        brightness = float(np.mean(gray))
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        analysis = {
            'duration': 0,
            'fps': 0,
            'resolution': {'width': width, 'height': height},
            'frame_count': 1,
            'brightness': round(brightness, 2),
            'motion_segments': [],
            'quiet_segments': [],
            'has_audio': False,
            'estimated_reps': 0,
            'is_image': True,
            'suggestions': []
        }

        if brightness < 80:
            analysis['suggestions'].append({
                'type': 'brightness',
                'icon': '☀️',
                'title': 'Low Brightness',
                'description': 'Image appears dark',
                'fix': 'Increase brightness by 20-30%'
            })
        elif brightness > 200:
            analysis['suggestions'].append({
                'type': 'brightness',
                'icon': '🔆',
                'title': 'Overexposed',
                'description': 'Image is too bright',
                'fix': 'Decrease brightness'
            })

        if sharpness < 100:
            analysis['suggestions'].append({
                'type': 'sharpness',
                'icon': '🔍',
                'title': 'Blurry Image',
                'description': 'Image appears out of focus',
                'fix': 'Apply a sharpening filter'
            })

        if width > height:
            analysis['suggestions'].append({
                'type': 'crop',
                'icon': '📐',
                'title': 'Landscape Orientation',
                'description': 'Image is wider than tall',
                'fix': 'Crop to 9:16 for Reels/TikTok'
            })

        self.analysis = analysis
        return analysis
