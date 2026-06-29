from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
import os
import json
import subprocess
import threading
from datetime import timedelta
import cv2
import numpy as np
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'outputs'
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB

# Create folders
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

ALLOWED_VIDEO = {'mp4', 'mov', 'avi', 'mkv', 'webm'}
ALLOWED_IMAGE = {'jpg', 'jpeg', 'png', 'webp'}
ALLOWED_AUDIO = {'mp3', 'wav', 'aac', 'ogg'}

# Store processing status
processing_status = {}


def allowed_file(filename, file_type='video'):
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    if file_type == 'video':
        return ext in ALLOWED_VIDEO
    elif file_type == 'image':
        return ext in ALLOWED_IMAGE
    elif file_type == 'audio':
        return ext in ALLOWED_AUDIO
    return False


def get_video_info(video_path):
    """Get video metadata using ffprobe"""
    cmd = [
        'ffprobe', '-v', 'error', '-print_format', 'json',
        '-show_format', '-show_streams', video_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        return json.loads(result.stdout)
    except:
        return {}


def analyze_video(video_path, task_id):
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
        step = max(1, frame_count // total_frames)
        
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
                    'title': 'Long Rest Period',
                    'description': f'{q["duration"]}s rest at {format_time(q["start_time"])}',
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


def format_time(seconds):
    return str(timedelta(seconds=int(seconds)))[2:7]


def generate_claude_prompt(analysis, preferences):
    """Generate Claude prompt from analysis"""
    a = analysis
    
    prompt = f"""I have a workout video that needs editing. Here's the automatic analysis:

## VIDEO ANALYSIS RESULTS:
- **Duration**: {a['duration']} seconds ({format_time(a['duration'])})
- **Resolution**: {a['resolution']['width']}x{a['resolution']['height']}
- **FPS**: {a['fps']}
- **Brightness Level**: {a['brightness']}/255 ({'dark' if a['brightness'] < 80 else 'normal' if a['brightness'] < 200 else 'bright'})
- **Has Audio**: {'Yes' if a['has_audio'] else 'No'}
- **Motion Segments Found**: {len(a['motion_segments'])}
- **Estimated Reps**: {a['estimated_reps']}"""
    
    if a['motion_segments']:
        prompt += "\n\n### DETECTED EXERCISE SEGMENTS:\n"
        for i, seg in enumerate(a['motion_segments'][:10]):
            prompt += f"{i+1}. {format_time(seg['start_time'])} - {format_time(seg['end_time'])} ({seg['duration']}s"
            if 'estimated_reps' in seg:
                prompt += f", ~{seg['estimated_reps']} reps"
            prompt += ")\n"
    
    if a['suggestions']:
        prompt += "\n### AUTO-DETECTED ISSUES:\n"
        for sug in a['suggestions']:
            prompt += f"- {sug['icon']} {sug['title']}: {sug['description']} → {sug['fix']}\n"
    
    prompt += f"""
## MY EDITING PREFERENCES:
- **Workout Type**: {preferences.get('workout_type', 'Not specified')}
- **Desired Mood**: {preferences.get('mood', 'Energetic')}
- **Target Platform**: {preferences.get('platform', 'Instagram Reels')}
- **Add Music**: {'Yes - ' + preferences.get('music_file', 'auto') if preferences.get('add_music') else 'No'}

## GENERATE FOR ME:
1. Complete FFmpeg command(s) for all edits
2. Text overlays with exercise names
3. Music/audio integration
4. Color correction if needed
5. Output settings for {preferences.get('platform', 'Instagram Reels')}"""
    
    return prompt


def execute_ffmpeg(commands, task_id, input_file, output_file):
    """Execute FFmpeg commands"""
    try:
        processing_status[task_id]['status'] = 'processing'
        
        current_input = input_file
        temp_outputs = []
        
        for i, cmd_info in enumerate(commands):
            processing_status[task_id]['current_step'] = cmd_info.get('name', f'Step {i+1}')
            processing_status[task_id]['progress'] = (i / len(commands)) * 100
            
            # Replace input/output placeholders
            cmd = cmd_info['command']
            cmd = cmd.replace('{INPUT}', current_input)
            
            if i == len(commands) - 1:
                cmd = cmd.replace('{OUTPUT}', output_file)
            else:
                temp_output = f"temp_{i}_{output_file}"
                cmd = cmd.replace('{OUTPUT}', temp_output)
                temp_outputs.append(temp_output)
            
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode != 0:
                processing_status[task_id]['status'] = 'error'
                processing_status[task_id]['error'] = result.stderr[:500]
                # Cleanup temp files
                for t in temp_outputs:
                    if os.path.exists(t):
                        os.remove(t)
                return
            
            if i < len(commands) - 1 and os.path.exists(temp_output):
                current_input = temp_output
        
        # Cleanup temp files
        for t in temp_outputs:
            if os.path.exists(t):
                os.remove(t)
        
        processing_status[task_id]['status'] = 'completed'
        processing_status[task_id]['progress'] = 100
        processing_status[task_id]['output_file'] = output_file
        
    except Exception as e:
        processing_status[task_id]['status'] = 'error'
        processing_status[task_id]['error'] = str(e)


# ============= ROUTES =============

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'video' not in request.files:
        return jsonify({'error': 'No video file'}), 400
    
    file = request.files['video']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename, 'video'):
        return jsonify({'error': 'Invalid video format'}), 400
    
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    
    # Handle music file if provided
    music_path = None
    if 'music' in request.files and request.files['music'].filename:
        music_file = request.files['music']
        if allowed_file(music_file.filename, 'audio'):
            music_filename = secure_filename(music_file.filename)
            music_path = os.path.join(app.config['UPLOAD_FOLDER'], music_filename)
            music_file.save(music_path)
    
    # Create task
    task_id = filename.replace('.', '_') + '_' + str(int(hash(filename) % 100000))
    processing_status[task_id] = {
        'filename': filename,
        'filepath': filepath,
        'music_path': music_path,
        'status': 'uploaded',
        'progress': 0,
        'analysis': None,
        'error': None
    }
    
    return jsonify({
        'task_id': task_id,
        'filename': filename,
        'message': 'File uploaded successfully'
    })


@app.route('/api/analyze/<task_id>', methods=['POST'])
def start_analysis(task_id):
    if task_id not in processing_status:
        return jsonify({'error': 'Task not found'}), 404
    
    # Start analysis in background
    thread = threading.Thread(
        target=analyze_video,
        args=(processing_status[task_id]['filepath'], task_id)
    )
    thread.start()
    
    return jsonify({'message': 'Analysis started'})


@app.route('/api/status/<task_id>')
def get_status(task_id):
    if task_id not in processing_status:
        return jsonify({'error': 'Task not found'}), 404
    
    status = processing_status[task_id]
    return jsonify({
        'status': status['status'],
        'progress': status['progress'],
        'analysis': status.get('analysis'),
        'error': status.get('error'),
        'current_step': status.get('current_step')
    })


@app.route('/api/generate-prompt', methods=['POST'])
def generate_prompt():
    data = request.json
    analysis = data.get('analysis')
    preferences = data.get('preferences', {})
    
    if not analysis:
        return jsonify({'error': 'No analysis data'}), 400
    
    prompt = generate_claude_prompt(analysis, preferences)
    
    return jsonify({'prompt': prompt})


@app.route('/api/generate-commands', methods=['POST'])
def generate_commands():
    data = request.json
    analysis = data.get('analysis')
    preferences = data.get('preferences', {})
    task_id = data.get('task_id')
    
    if not analysis or not task_id:
        return jsonify({'error': 'Missing data'}), 400
    
    task = processing_status.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    
    commands = []
    input_file = task['filepath']
    output_filename = f"edited_{task['filename']}"
    output_file = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
    
    platform = preferences.get('platform', 'instagram-reels')
    
    # Brightness fix
    if analysis['brightness'] < 80:
        brightness_val = min(0.3, (100 - analysis['brightness']) / 300)
        commands.append({
            'name': 'Fix Brightness',
            'icon': '☀️',
            'command': f'ffmpeg -i "{{INPUT}}" -vf "eq=brightness={brightness_val}" -c:a copy "{{OUTPUT}}"'
        })
    elif analysis['brightness'] > 200:
        commands.append({
            'name': 'Reduce Brightness',
            'icon': '🔆',
            'command': f'ffmpeg -i "{{INPUT}}" -vf "eq=brightness=-0.1" -c:a copy "{{OUTPUT}}"'
        })
    
    # Crop for platform
    if platform in ['instagram-reels', 'tiktok']:
        commands.append({
            'name': 'Crop to 9:16',
            'icon': '📐',
            'command': f'ffmpeg -i "{{INPUT}}" -vf "crop=ih*9/16:ih,scale=1080:1920,pad=1080:1920:(ow-iw)/2:(oh-ih)/2" -c:a copy "{{OUTPUT}}"'
        })
    elif platform == 'youtube':
        commands.append({
            'name': 'Scale to 1080p',
            'icon': '📐',
            'command': f'ffmpeg -i "{{INPUT}}" -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2" -c:a copy "{{OUTPUT}}"'
        })
    
    # Add text overlays
    workout_type = preferences.get('workout_type', '').upper() or 'EXERCISE'
    for i, seg in enumerate(analysis['motion_segments'][:6]):
        if seg['duration'] > 1.5:
            duration = min(3, seg['duration'])
            commands.append({
                'name': f'Add Text: {workout_type} #{i+1}',
                'icon': '📝',
                'command': f'''ffmpeg -i "{{INPUT}}" -vf "drawtext=text='{workout_type} %{i+1}':fontsize=50:fontcolor=white:x=(w-text_w)/2:y=50:boxcolor=black@0.6:box=1:enable='between(t,{seg["start_time"]},{seg["start_time"] + duration})'" -c:a copy "{{OUTPUT}}"'''
            })
    
    # Add music
    if preferences.get('add_music') and task.get('music_path'):
        music_path = task['music_path']
        volume = preferences.get('music_volume', 0.15)
        commands.append({
            'name': 'Add Background Music',
            'icon': '🎵',
            'command': f'ffmpeg -i "{{INPUT}}" -i "{music_path}" -stream_loop -1 -filter_complex "[1:a]volume={volume}[bgm]" -map 0:v -map "[bgm]" -c:v copy -shortest "{{OUTPUT}}"'
        })
    
    # Fade in/out
    commands.append({
        'name': 'Add Fade Effects',
        'icon': '✨',
        'command': f'ffmpeg -i "{{INPUT}}" -vf "fade=t=in:st=0:d=0.5,fade=t=out:st={analysis["duration"]-0.5}:d=0.5" -af "afade=t=in:st=0:d=0.5,afade=t=out:st={analysis["duration"]-0.5}:d=0.5" "{{OUTPUT}}"'
    })
    
    # Final optimization
    if platform == 'instagram-reels':
        commands.append({
            'name': 'Optimize for Reels',
            'icon': '🚀',
            'command': f'ffmpeg -i "{{INPUT}}" -c:v libx264 -preset medium -crf 23 -c:a aac -b:a 128k -movflags +faststart "{{OUTPUT}}"'
        })
    elif platform == 'youtube':
        commands.append({
            'name': 'Optimize for YouTube',
            'icon': '🚀',
            'command': f'ffmpeg -i "{{INPUT}}" -c:v libx264 -preset slow -crf 20 -c:a aac -b:a 192k -movflags +faststart "{{OUTPUT}}"'
        })
    
    processing_status[task_id]['commands'] = commands
    processing_status[task_id]['output_file'] = output_file
    
    return jsonify({'commands': commands})


@app.route('/api/execute', methods=['POST'])
def execute_commands():
    data = request.json
    task_id = data.get('task_id')
    commands = data.get('commands', [])
    
    if not task_id or not commands:
        return jsonify({'error': 'Missing data'}), 400
    
    task = processing_status.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    
    output_filename = f"edited_{task['filename']}"
    output_file = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
    
    thread = threading.Thread(
        target=execute_ffmpeg,
        args=(commands, task_id, task['filepath'], output_file)
    )
    thread.start()
    
    return jsonify({'message': 'Processing started'})


@app.route('/api/download/<task_id>')
def download_file(task_id):
    task = processing_status.get(task_id)
    if not task or task['status'] != 'completed':
        return jsonify({'error': 'File not ready'}), 404
    
    output_file = task.get('output_file')
    if not output_file or not os.path.exists(output_file):
        return jsonify({'error': 'Output file not found'}), 404
    
    return send_file(output_file, as_attachment=True)


@app.route('/api/cancel/<task_id>', methods=['POST'])
def cancel_task(task_id):
    if task_id in processing_status:
        processing_status[task_id]['status'] = 'cancelled'
        return jsonify({'message': 'Task cancelled'})
    return jsonify({'error': 'Task not found'}), 404


# For mobile PWA manifest
@app.route('/manifest.json')
def manifest():
    return jsonify({
        "name": "Workout Video Editor",
        "short_name": "WorkoutEdit",
        "description": "AI-powered workout video editor",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0f0f1a",
        "theme_color": "#6c5ce7",
        "orientation": "portrait",
        "icons": [
            {
                "src": "/static/icon-192.png",
                "sizes": "192x192",
                "type": "image/png"
            },
            {
                "src": "/static/icon-512.png",
                "sizes": "512x512",
                "type": "image/png"
            }
        ]
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)