"""Generate the Claude editing prompt from analysis results."""
from analyzer.video_analyzer import format_time


def generate_image_prompt(analysis, preferences):
    """Generate Claude prompt for a still image"""
    a = analysis

    prompt = f"""I have a workout photo that needs editing. Here's the automatic analysis:

## IMAGE ANALYSIS RESULTS:
- **Resolution**: {a['resolution']['width']}x{a['resolution']['height']}
- **Orientation**: {'landscape' if a['resolution']['width'] > a['resolution']['height'] else 'portrait'}
- **Brightness Level**: {a['brightness']}/255 ({'dark' if a['brightness'] < 80 else 'normal' if a['brightness'] < 200 else 'bright'})"""

    if a['suggestions']:
        prompt += "\n\n### AUTO-DETECTED ISSUES:\n"
        for sug in a['suggestions']:
            prompt += f"- {sug['icon']} {sug['title']}: {sug['description']} → {sug['fix']}\n"

    prompt += f"""
## MY EDITING PREFERENCES:
- **Workout Type**: {preferences.get('workout_type', 'Not specified')}
- **Desired Mood**: {preferences.get('mood', 'Energetic')}
- **Target Platform**: {preferences.get('platform', 'Instagram Reels')}
- **Output Resolution**: {preferences.get('resolution', '1080p')}

## GENERATE FOR ME:
1. Complete FFmpeg command(s) for all image edits
2. Text overlay with the workout name
3. Color/brightness correction if needed
4. Crop/resize settings for {preferences.get('platform', 'Instagram Reels')}"""

    return prompt


def generate_claude_prompt(analysis, preferences):
    """Generate Claude prompt from analysis"""
    if analysis.get('is_image'):
        return generate_image_prompt(analysis, preferences)

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
- **Output Resolution**: {preferences.get('resolution', '1080p')}
- **Add Music**: {'Yes - ' + preferences.get('music_file', 'auto') if preferences.get('add_music') else 'No'}

## GENERATE FOR ME:
1. Complete FFmpeg command(s) for all edits
2. Text overlays with exercise names
3. Music/audio integration
4. Color correction if needed
5. Output settings for {preferences.get('platform', 'Instagram Reels')}"""

    return prompt
