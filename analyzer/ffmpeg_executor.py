"""Build and execute FFmpeg command pipelines.

Commands are stored as template strings with {INPUT}/{OUTPUT} placeholders.
Execution never goes through a shell: each command is split with shlex and
must invoke the ffmpeg binary, so shell metacharacters in pasted text are
passed to ffmpeg as literal arguments instead of being interpreted.
"""
import os
import platform
import re
import shlex
import subprocess


def run_ffmpeg_pipeline(commands, task_id, input_file, output_file, processing_status):
    """Run a list of command dicts as a pipeline, chaining outputs to inputs."""
    try:
        processing_status[task_id]['status'] = 'processing'
        processing_status[task_id]['progress'] = 0

        output_dir = os.path.dirname(output_file) or '.'
        output_name = os.path.basename(output_file)
        os.makedirs(output_dir, exist_ok=True)

        current_input = input_file
        temp_outputs = []

        def cleanup_temps():
            for t in temp_outputs:
                if os.path.exists(t):
                    os.remove(t)

        for i, cmd_info in enumerate(commands):
            processing_status[task_id]['current_step'] = cmd_info.get('name', f'Step {i+1}')
            processing_status[task_id]['progress'] = (i / len(commands)) * 100

            cmd = cmd_info['command']
            cmd = cmd.replace('{INPUT}', current_input)

            if i == len(commands) - 1:
                step_output = output_file
            else:
                step_output = os.path.join(output_dir, f'temp_{i}_{output_name}')
                temp_outputs.append(step_output)
            cmd = cmd.replace('{OUTPUT}', step_output)

            args = shlex.split(cmd)
            if not args or os.path.basename(args[0]) != 'ffmpeg':
                processing_status[task_id]['status'] = 'error'
                processing_status[task_id]['error'] = 'Refused: only ffmpeg commands can be executed'
                cleanup_temps()
                return
            if '-y' not in args:
                args.insert(1, '-y')

            result = subprocess.run(args, capture_output=True, text=True)

            if result.returncode != 0:
                processing_status[task_id]['status'] = 'error'
                # Last 500 chars of stderr hold the actual error, not the banner
                processing_status[task_id]['error'] = result.stderr[-500:]
                cleanup_temps()
                return

            if i < len(commands) - 1 and os.path.exists(step_output):
                current_input = step_output

        cleanup_temps()

        processing_status[task_id]['status'] = 'completed'
        processing_status[task_id]['progress'] = 100
        processing_status[task_id]['output_file'] = output_file

    except Exception as e:
        processing_status[task_id]['status'] = 'error'
        processing_status[task_id]['error'] = str(e)


def build_image_commands(analysis, preferences):
    """Build the auto-edit pipeline for a still image (no audio/fade/video codecs)."""
    commands = []
    platform_choice = preferences.get('platform', 'instagram-reels')

    # Brightness fix
    if analysis['brightness'] < 80:
        brightness_val = min(0.3, (100 - analysis['brightness']) / 300)
        commands.append({
            'name': 'Fix Brightness',
            'icon': '☀️',
            'command': f'ffmpeg -i "{{INPUT}}" -vf "eq=brightness={brightness_val}" "{{OUTPUT}}"'
        })
    elif analysis['brightness'] > 200:
        commands.append({
            'name': 'Reduce Brightness',
            'icon': '🔆',
            'command': 'ffmpeg -i "{INPUT}" -vf "eq=brightness=-0.1" "{OUTPUT}"'
        })

    # Sharpen if the analyzer flagged blur
    if any(s.get('type') == 'sharpness' for s in analysis.get('suggestions', [])):
        commands.append({
            'name': 'Sharpen Image',
            'icon': '🔍',
            'command': 'ffmpeg -i "{INPUT}" -vf "unsharp=5:5:1.0" "{OUTPUT}"'
        })

    # Resize/pad for platform (scale+pad is safe for any orientation)
    if platform_choice in ['instagram-reels', 'tiktok']:
        commands.append({
            'name': 'Fit to 9:16',
            'icon': '📐',
            'command': 'ffmpeg -i "{INPUT}" -vf "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2" "{OUTPUT}"'
        })
    elif platform_choice == 'youtube':
        commands.append({
            'name': 'Fit to 16:9',
            'icon': '📐',
            'command': 'ffmpeg -i "{INPUT}" -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2" "{OUTPUT}"'
        })

    # Workout label overlay
    if preferences.get('add_text', True):
        workout_type = preferences.get('workout_type', '').upper() or 'WORKOUT'
        commands.append({
            'name': f'Add Text: {workout_type}',
            'icon': '📝',
            'command': f'''ffmpeg -i "{{INPUT}}" -vf "drawtext=text='{workout_type}':fontsize=50:fontcolor=white:x=(w-text_w)/2:y=50:boxcolor=black@0.6:box=1" "{{OUTPUT}}"'''
        })

    if not commands:
        # Always produce at least one step so export has something to run
        commands.append({
            'name': 'Export Image',
            'icon': '🖼️',
            'command': 'ffmpeg -i "{INPUT}" -q:v 2 "{OUTPUT}"'
        })

    return commands


def build_commands(analysis, preferences, music_path):
    """Build the auto-edit pipeline from analysis results and user preferences."""
    if analysis.get('is_image'):
        return build_image_commands(analysis, preferences)

    commands = []
    platform_choice = preferences.get('platform', 'instagram-reels')

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
            'command': 'ffmpeg -i "{INPUT}" -vf "eq=brightness=-0.1" -c:a copy "{OUTPUT}"'
        })

    # Crop for platform
    if platform_choice in ['instagram-reels', 'tiktok']:
        commands.append({
            'name': 'Crop to 9:16',
            'icon': '📐',
            'command': 'ffmpeg -i "{INPUT}" -vf "crop=ih*9/16:ih,scale=1080:1920,pad=1080:1920:(ow-iw)/2:(oh-ih)/2" -c:a copy "{OUTPUT}"'
        })
    elif platform_choice == 'youtube':
        commands.append({
            'name': 'Scale to 1080p',
            'icon': '📐',
            'command': 'ffmpeg -i "{INPUT}" -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2" -c:a copy "{OUTPUT}"'
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

    # Add music (-stream_loop must precede the input it applies to)
    if preferences.get('add_music') and music_path:
        volume = preferences.get('music_volume', 0.15)
        commands.append({
            'name': 'Add Background Music',
            'icon': '🎵',
            'command': f'ffmpeg -i "{{INPUT}}" -stream_loop -1 -i "{music_path}" -filter_complex "[1:a]volume={volume}[bgm]" -map 0:v -map "[bgm]" -c:v copy -shortest "{{OUTPUT}}"'
        })

    # Fade in/out
    commands.append({
        'name': 'Add Fade Effects',
        'icon': '✨',
        'command': f'ffmpeg -i "{{INPUT}}" -vf "fade=t=in:st=0:d=0.5,fade=t=out:st={analysis["duration"]-0.5}:d=0.5" -af "afade=t=in:st=0:d=0.5,afade=t=out:st={analysis["duration"]-0.5}:d=0.5" "{{OUTPUT}}"'
    })

    # Final optimization
    if platform_choice == 'instagram-reels':
        commands.append({
            'name': 'Optimize for Reels',
            'icon': '🚀',
            'command': 'ffmpeg -i "{INPUT}" -c:v libx264 -preset medium -crf 23 -c:a aac -b:a 128k -movflags +faststart "{OUTPUT}"'
        })
    elif platform_choice == 'youtube':
        commands.append({
            'name': 'Optimize for YouTube',
            'icon': '🚀',
            'command': 'ffmpeg -i "{INPUT}" -c:v libx264 -preset slow -crf 20 -c:a aac -b:a 192k -movflags +faststart "{OUTPUT}"'
        })

    return commands


def parse_claude_commands(claude_text, input_path, output_path):
    """Extract ffmpeg commands from pasted Claude output and pin file paths
    to the task's real input/output files."""
    lines = claude_text.split('\n')
    full_command = ""
    extracted_commands = []

    for line in lines:
        stripped = line.rstrip()

        is_continuation = stripped.endswith('\\')
        if is_continuation:
            stripped = stripped[:-1].rstrip()

        if stripped.startswith('#') or stripped.startswith('```') or not stripped:
            continue

        if stripped.startswith('ffmpeg'):
            if full_command:
                extracted_commands.append(full_command.strip())
            full_command = stripped + " "
        elif full_command:
            if is_continuation:
                full_command += stripped
            else:
                full_command += stripped + " "

    if full_command:
        extracted_commands.append(full_command.strip())

    final_commands = []
    input_path = input_path.replace('\\', '/')
    output_path = output_path.replace('\\', '/')

    for cmd in extracted_commands:
        # Fix input file: replace the first -i argument (quoted or bare)
        if '{INPUT}' in cmd:
            cmd = cmd.replace('{INPUT}', input_path)
        else:
            cmd = re.sub(r'(-i\s+)("[^"]*"|\S+)', fr'\1"{input_path}"', cmd, count=1)

        # Fix output file: the trailing video filename
        if '{OUTPUT}' in cmd:
            cmd = cmd.replace('{OUTPUT}', output_path)
        else:
            cmd = re.sub(r'(\s)\S+\.(?:mp4|mov|avi|mkv|webm)(\s*)$', fr'\1"{output_path}"\2', cmd)

        # Fix font paths based on OS
        if platform.system() == 'Windows':
            cmd = cmd.replace('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 'C\\:/Windows/Fonts/arialbd.ttf')
        elif platform.system() == 'Darwin':  # Mac
            cmd = cmd.replace('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/System/Library/Fonts/Supplemental/Arial Bold.ttf')

        final_commands.append({
            'name': f'Claude Command {len(final_commands)+1}',
            'icon': '🤖',
            'command': cmd
        })

    return final_commands
