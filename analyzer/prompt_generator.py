"""Generate the Claude editing prompt from analysis results."""
from analyzer.video_analyzer import format_time


def generate_image_prompt(analysis, preferences):
    """Generate Claude prompt for a still image"""
    a = analysis

    prompt = f"""I have a photo that needs editing. Here's the automatic analysis:

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
- **Content Label**: {preferences.get('workout_type', 'Not specified')}
- **Desired Mood**: {preferences.get('mood', 'Energetic')}
- **Target Platform**: {preferences.get('platform', 'Instagram Reels')}
- **Output Resolution**: {preferences.get('resolution', '1080p')}

## EDITS TO CONSIDER (include ONLY the ones actually needed per the analysis and preferences above):
- Text overlay with the content label (skip if no label was specified)
- Color/brightness correction (skip if brightness is normal)
- Crop/resize for {preferences.get('platform', 'Instagram Reels')}

## YOUR TASK — READ CAREFULLY:
The image file itself is NOT attached and cannot be shared — the analysis above is ALL the information available, and it is enough. My local editing tool will run your commands and substitute the real file paths.
Reply with ONLY the FFmpeg command(s), in a single code block — no explanations, no alternatives, no manual steps, no other tools.
Use {{INPUT}} as the input file path and {{OUTPUT}} as the output file path in every command.
The input is a STILL IMAGE and the output must also be a still image (JPEG). Never use video codecs or video encoding settings (-c:v libx264, -crf, -preset, -movflags, etc.) — even when the target platform is a video site, the deliverable is an image. Use -q:v 2 for JPEG quality.
Do NOT ask clarifying questions. If something is ambiguous, pick the standard option yourself — e.g. if the source orientation doesn't match the platform's aspect ratio, scale to fit inside the target frame and pad the rest (scale=W:H:force_original_aspect_ratio=decrease + pad), never crop content away."""

    return prompt


def generate_claude_prompt(analysis, preferences):
    """Generate Claude prompt from analysis"""
    if analysis.get('is_image'):
        return generate_image_prompt(analysis, preferences)

    a = analysis

    prompt = f"""I have a video that needs editing. Here's the automatic analysis:

## VIDEO ANALYSIS RESULTS:
- **Duration**: {a['duration']} seconds ({format_time(a['duration'])})
- **Resolution**: {a['resolution']['width']}x{a['resolution']['height']}
- **FPS**: {a['fps']}
- **Brightness Level**: {a['brightness']}/255 ({'dark' if a['brightness'] < 80 else 'normal' if a['brightness'] < 200 else 'bright'})
- **Has Audio**: {'Yes' if a['has_audio'] else 'No'}
- **Action Segments Found**: {len(a['motion_segments'])}
"""

    if a['motion_segments']:
        prompt += "\n\n### DETECTED ACTION SEGMENTS:\n"
        for i, seg in enumerate(a['motion_segments'][:10]):
            prompt += f"{i+1}. {format_time(seg['start_time'])} - {format_time(seg['end_time'])} ({seg['duration']}s)\n"

    if a['suggestions']:
        prompt += "\n### AUTO-DETECTED ISSUES:\n"
        for sug in a['suggestions']:
            prompt += f"- {sug['icon']} {sug['title']}: {sug['description']} → {sug['fix']}\n"

    prompt += f"""
## MY EDITING PREFERENCES:
- **Content Label**: {preferences.get('workout_type', 'Not specified')}
- **Desired Mood**: {preferences.get('mood', 'Energetic')}
- **Target Platform**: {preferences.get('platform', 'Instagram Reels')}
- **Output Resolution**: {preferences.get('resolution', '1080p')}
- **Add Music**: {'Yes - ' + preferences.get('music_file', 'auto') if preferences.get('add_music') else 'No'}

## EDITS TO CONSIDER (include ONLY the ones actually needed per the analysis and preferences above):
- Text overlays with the content label (skip if no label was specified)
- Music/audio integration (skip if Add Music is No)
- Color/brightness correction (skip if brightness is normal)
- Crop/scale and encoding settings for {preferences.get('platform', 'Instagram Reels')}

## YOUR TASK — READ CAREFULLY:
The video file itself is NOT attached and cannot be shared — the analysis above is ALL the information available, and it is enough. My local editing tool will run your commands and substitute the real file paths.
Reply with ONLY the FFmpeg command(s), in a single code block — no explanations, no alternatives, no manual steps, no other tools.
Use {{INPUT}} as the input file path and {{OUTPUT}} as the output file path in every command.
Do NOT ask clarifying questions. If something is ambiguous, pick the standard option yourself — e.g. if the source orientation doesn't match the platform's aspect ratio, scale to fit inside the target frame and pad the rest (scale=W:H:force_original_aspect_ratio=decrease + pad), never crop content away."""

    return prompt
