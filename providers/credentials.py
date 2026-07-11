"""Credential manager: resolve each provider's API key from the environment.

Mirrors the existing OPENAI_API_KEY + python-dotenv pattern in app.py.
Keys are read from env vars named in providers.json (api_key_env). No key is
ever logged or returned to the frontend — only presence is reported.
"""
import logging
import os

log = logging.getLogger('providers.credentials')


class CredentialManager:
    def __init__(self, registry: dict):
        self._registry = registry
        # provider_id -> bool (credential present / not required)
        self._available: dict[str, bool] = {}
        self.validate_all()

    def validate_all(self) -> dict:
        """Recompute availability from the current environment. Called on startup."""
        self._available = {}
        for pid, p in self._registry.items():
            if p.auth_type == 'none':
                self._available[pid] = True
                continue
            key = os.environ.get(p.api_key_env or '', '').strip()
            self._available[pid] = bool(key)
        self._log_summary()
        return dict(self._available)

    def has_credentials(self, provider_id: str) -> bool:
        return self._available.get(provider_id, False)

    def get_key(self, provider_id: str) -> str | None:
        """Return the raw key for making a real call. Never expose to clients."""
        p = self._registry.get(provider_id)
        if not p or p.auth_type == 'none':
            return None
        return os.environ.get(p.api_key_env or '', '').strip() or None

    def _log_summary(self) -> None:
        ready = [pid for pid, ok in self._available.items() if ok]
        missing = [pid for pid, ok in self._available.items() if not ok]
        log.info('Providers with credentials: %s', ', '.join(ready) or '(none)')
        if missing:
            log.info('Providers missing credentials (marked unavailable): %s', ', '.join(missing))
