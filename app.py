from flask import Flask, render_template, request, jsonify, send_file
import os
import shutil
import threading
import time
import uuid
from werkzeug.utils import secure_filename

from analyzer.video_analyzer import analyze_video
from analyzer.image_analyzer import WorkoutImageAnalyzer
from analyzer.prompt_generator import generate_claude_prompt
from analyzer.ffmpeg_executor import build_commands, parse_claude_commands, run_ffmpeg_pipeline

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

# Task folders older than this are deleted on the next upload
TASK_TTL_SECONDS = int(os.environ.get('TASK_TTL_HOURS', '24')) * 3600


def cleanup_old_tasks():
    """Delete per-task upload/output directories older than TASK_TTL_SECONDS."""
    now = time.time()
    for folder in (app.config['UPLOAD_FOLDER'], app.config['OUTPUT_FOLDER']):
        if not os.path.isdir(folder):
            continue
        for entry in os.listdir(folder):
            path = os.path.join(folder, entry)
            # Only task directories; loose legacy files and .gitkeep stay
            if not os.path.isdir(path):
                continue
            try:
                if now - os.path.getmtime(path) > TASK_TTL_SECONDS:
                    shutil.rmtree(path, ignore_errors=True)
                    processing_status.pop(entry, None)
            except OSError:
                continue


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


def is_image_file(filename):
    return filename.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))


def output_path_for(task_id, task):
    return os.path.join(app.config['OUTPUT_FOLDER'], task_id, f"edited_{task['filename']}")


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

    file_type = 'image' if is_image_file(file.filename) else 'video'
    if not allowed_file(file.filename, file_type):
        return jsonify({'error': f'Invalid {file_type} format'}), 400

    cleanup_old_tasks()

    task_id = uuid.uuid4().hex[:12]
    task_dir = os.path.join(app.config['UPLOAD_FOLDER'], task_id)
    os.makedirs(task_dir, exist_ok=True)

    filename = secure_filename(file.filename) or f'upload.{file.filename.rsplit(".", 1)[1].lower()}'
    filepath = os.path.join(task_dir, filename)
    file.save(filepath)

    # Handle music file if provided
    music_path = None
    if 'music' in request.files and request.files['music'].filename:
        music_file = request.files['music']
        if allowed_file(music_file.filename, 'audio'):
            music_filename = secure_filename(music_file.filename)
            music_path = os.path.join(task_dir, music_filename)
            music_file.save(music_path)

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

    task = processing_status[task_id]

    if is_image_file(task['filename']):
        # Analyze image instantly (no need for background thread)
        try:
            img_analyzer = WorkoutImageAnalyzer(task['filepath'])
            img_analyzer.analyze()
            task['analysis'] = img_analyzer.analysis
            task['status'] = 'analyzed'
            task['progress'] = 100
        except Exception as e:
            task['status'] = 'error'
            task['error'] = str(e)
    else:
        # Start video analysis in background
        thread = threading.Thread(
            target=analyze_video,
            args=(task['filepath'], task_id, processing_status)
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
    preferences = data.get('preferences', {})
    task_id = data.get('task_id')

    task = processing_status.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404

    analysis = task.get('analysis')
    if not analysis:
        return jsonify({'error': 'Analyze the file first'}), 400

    commands = build_commands(analysis, preferences, task.get('music_path'))

    task['commands'] = commands
    task['output_file'] = output_path_for(task_id, task)

    return jsonify({'commands': commands})


@app.route('/api/execute', methods=['POST'])
def execute_commands():
    data = request.json or {}
    task_id = data.get('task_id')

    task = processing_status.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404

    # Only run the commands this server generated for the task —
    # never command strings sent by the client.
    commands = task.get('commands')
    if not commands:
        return jsonify({'error': 'Generate commands first'}), 400

    thread = threading.Thread(
        target=run_ffmpeg_pipeline,
        args=(commands, task_id, task['filepath'], output_path_for(task_id, task), processing_status)
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

    # ?preview=true serves inline so <video>/<img> elements can display it
    as_attachment = request.args.get('preview') != 'true'
    return send_file(os.path.abspath(output_file), as_attachment=as_attachment)


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
        "name": "AI Media Editor",
        "short_name": "MediaEdit",
        "description": "AI-powered video and image editor",
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


@app.route('/api/run-claude-commands', methods=['POST'])
def run_claude_commands():
    data = request.json
    task_id = data.get('task_id')
    claude_text = data.get('claude_text', '')

    if not task_id or not claude_text:
        return jsonify({'error': 'Missing data'}), 400

    task = processing_status.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404

    output_file = output_path_for(task_id, task)
    final_commands = parse_claude_commands(claude_text, task['filepath'], output_file)

    if not final_commands:
        return jsonify({'error': 'No valid ffmpeg commands found in the pasted text.'}), 400

    thread = threading.Thread(
        target=run_ffmpeg_pipeline,
        args=(final_commands, task_id, task['filepath'], output_file, processing_status)
    )
    thread.start()

    return jsonify({'message': f'Executing {len(final_commands)} Claude command(s) with fixed paths'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
