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


def _generate(media: str):
    data = request.get_json(silent=True) or {}
    prompt = (data.get('prompt') or '').strip()
    if not prompt:
        return jsonify({'error': 'prompt is required'}), 400

    provider = (data.get('provider') or '').strip()
    # Everything except provider/prompt is passed through as generation options.
    options = {k: v for k, v in data.items() if k not in ('provider', 'prompt')}

    service = get_service()
    try:
        if not provider:
            provider = service.get_provider_for_task(f'{media}-gen')
        if media == 'image':
            result = service.generate_image(provider, prompt, options)
        else:
            result = service.generate_video(provider, prompt, options)
        return jsonify(result)
    except ProviderError as e:
        # 402-style condition (over budget / none available) — use 409 so the
        # frontend can distinguish "try later / switch provider" from bad input.
        return jsonify({'error': str(e), 'provider': provider or None}), 409


@ai_bp.post('/generate/image')
def generate_image():
    return _generate('image')


@ai_bp.post('/generate/video')
def generate_video():
    return _generate('video')
