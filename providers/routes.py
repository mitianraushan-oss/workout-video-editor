"""Flask Blueprint exposing the provider layer over HTTP.

Registered in app.py:  app.register_blueprint(ai_bp)

Endpoints (as specced):
  GET  /api/ai/status            -> all providers + budgets (+ dry_run flag)
  POST /api/ai/providers         -> available providers + budgets
  POST /api/ai/check-budget      -> { provider } -> budget snapshot
  POST /api/ai/generate/image    -> { provider?, prompt, ... } -> result
  POST /api/ai/generate/video    -> { provider?, prompt, ... } -> result

If `provider` is omitted on a generate call, the service auto-selects the best
available one for the task (free tier preferred). Errors return JSON + 4xx.
"""
import logging

from flask import Blueprint, jsonify, request

from providers.service import ProviderService, ProviderError

log = logging.getLogger('providers.routes')

ai_bp = Blueprint('ai', __name__, url_prefix='/api/ai')

# One shared service per process. Credentials are validated on construction.
_service: ProviderService | None = None


def get_service() -> ProviderService:
    global _service
    if _service is None:
        _service = ProviderService()
    return _service


@ai_bp.get('/status')
def status():
    return jsonify(get_service().get_all_status())


@ai_bp.post('/providers')
def providers():
    return jsonify({'providers': get_service().list_available()})


@ai_bp.post('/check-budget')
def check_budget():
    data = request.get_json(silent=True) or {}
    provider = (data.get('provider') or '').strip()
    if not provider:
        return jsonify({'error': 'provider is required'}), 400
    try:
        return jsonify({'provider': provider, 'budget': get_service().check_budget(provider)})
    except ProviderError as e:
        return jsonify({'error': str(e)}), 404


# Keys that must NEVER be treated as generation options or logged.
_SECRET_KEYS = {'api_key', 'apiKey', 'key'}
_RESERVED = {'provider', 'prompt'} | _SECRET_KEYS


def _options_from(data: dict) -> dict:
    """Pass-through options with provider/prompt AND any secret stripped out."""
    return {k: v for k, v in data.items() if k not in _RESERVED}


def _generate(media: str):
    data = request.get_json(silent=True) or {}
    prompt = (data.get('prompt') or '').strip()
    if not prompt:
        return jsonify({'error': 'prompt is required'}), 400

    provider = (data.get('provider') or '').strip()
    api_key = (data.get('api_key') or '').strip() or None  # BYO; never logged
    options = _options_from(data)

    service = get_service()
    try:
        if not provider:
            provider = service.get_provider_for_task(f'{media}-gen')
        if media == 'image':
            result = service.generate_image(provider, prompt, options, api_key=api_key)
        else:
            result = service.generate_video(provider, prompt, options, api_key=api_key)
        return jsonify(result)
    except ProviderError as e:
        # 409 = "try later / switch provider / needs key", distinct from 400 bad input.
        return jsonify({'error': str(e), 'provider': provider or None}), 409


@ai_bp.post('/generate/image')
def generate_image():
    return _generate('image')


@ai_bp.post('/generate/video')
def generate_video():
    return _generate('video')


@ai_bp.post('/edit/image')
def edit_image():
    """Image edit is multipart: an uploaded source image + prompt (+ api_key).
    The uploaded file is written to a temp path passed to the provider as an
    option; api_key is read from the form and never logged."""
    import os
    import tempfile
    from werkzeug.utils import secure_filename

    prompt = (request.form.get('prompt') or '').strip()
    provider = (request.form.get('provider') or '').strip()
    api_key = (request.form.get('api_key') or '').strip() or None
    if not prompt:
        return jsonify({'error': 'prompt is required'}), 400
    if 'image' not in request.files or not request.files['image'].filename:
        return jsonify({'error': 'an image file is required'}), 400

    f = request.files['image']
    tmp_dir = tempfile.mkdtemp()
    src = os.path.join(tmp_dir, secure_filename(f.filename) or 'input.png')
    f.save(src)

    service = get_service()
    try:
        if not provider:
            provider = service.get_provider_for_task('image-edit')
        result = service.edit_image(provider, prompt, {'input_path': src}, api_key=api_key)
        return jsonify(result)
    except ProviderError as e:
        return jsonify({'error': str(e), 'provider': provider or None}), 409
    finally:
        try:
            os.remove(src)
        except OSError:
            pass
