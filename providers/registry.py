"""Load and validate config/providers.json into Provider objects.

The registry is the single source of truth for *static* provider facts
(types, auth, free-tier shape, endpoints, limits). Live state — credentials
and remaining budget — lives in credentials.py and usage.py respectively.
"""
import json
import os
from dataclasses import dataclass, field

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'providers.json')

TASK_TYPES = {'image-gen', 'video-gen', 'image-edit', 'video-edit', 'upscale', '3d-gen'}
FREE_TIER_TYPES = {'daily-credits', 'one-time-credits', 'free-rate-limited', 'paid-only'}


@dataclass
class Provider:
    name: str
    id: str
    types: list
    auth_type: str
    api_key_env: str | None
    free_tier_type: str
    free_tier_limit: object  # int, or {"per_minute","per_day"}, or None
    cost_per_unit_usd: float | None
    base_url: str
    endpoints: dict = field(default_factory=dict)
    rate_limit: dict = field(default_factory=dict)
    priority: int = 100
    enabled: bool = True

    def supports(self, task_type: str) -> bool:
        return task_type in self.types

    def per_day_cap(self) -> int | None:
        """Daily unit cap this provider enforces, or None if uncapped/one-time."""
        if self.free_tier_type == 'daily-credits' and isinstance(self.free_tier_limit, int):
            return self.free_tier_limit
        rl = self.rate_limit or {}
        return rl.get('per_day')

    def to_public_dict(self) -> dict:
        """Static fields safe to expose to the frontend (no secrets)."""
        return {
            'name': self.name,
            'id': self.id,
            'types': self.types,
            'free_tier_type': self.free_tier_type,
            'free_tier_limit': self.free_tier_limit,
            'cost_per_unit_usd': self.cost_per_unit_usd,
            'rate_limit': self.rate_limit,
            'priority': self.priority,
            'enabled': self.enabled,
        }


class RegistryError(ValueError):
    pass


def _validate(raw: dict) -> None:
    if raw.get('auth_type') not in {'api-key', 'none'}:
        raise RegistryError(f"provider {raw.get('id')!r}: bad auth_type {raw.get('auth_type')!r}")
    if raw.get('free_tier_type') not in FREE_TIER_TYPES:
        raise RegistryError(f"provider {raw.get('id')!r}: bad free_tier_type {raw.get('free_tier_type')!r}")
    unknown = set(raw.get('types', [])) - TASK_TYPES
    if unknown:
        raise RegistryError(f"provider {raw.get('id')!r}: unknown types {sorted(unknown)}")
    if raw.get('auth_type') == 'api-key' and not raw.get('api_key_env'):
        raise RegistryError(f"provider {raw.get('id')!r}: api-key auth requires api_key_env")


def load_registry(path: str = CONFIG_PATH) -> dict:
    """Return {provider_id: Provider}. Ignores keys starting with '_' (docs)."""
    with open(path) as f:
        data = json.load(f)

    registry: dict[str, Provider] = {}
    for raw in data.get('providers', []):
        _validate(raw)
        p = Provider(
            name=raw['name'],
            id=raw['id'],
            types=raw['types'],
            auth_type=raw['auth_type'],
            api_key_env=raw.get('api_key_env'),
            free_tier_type=raw['free_tier_type'],
            free_tier_limit=raw.get('free_tier_limit'),
            cost_per_unit_usd=raw.get('cost_per_unit_usd'),
            base_url=raw.get('base_url', ''),
            endpoints=raw.get('endpoints', {}),
            rate_limit=raw.get('rate_limit', {}),
            priority=raw.get('priority', 100),
            enabled=raw.get('enabled', True),
        )
        if p.id in registry:
            raise RegistryError(f"duplicate provider id {p.id!r}")
        registry[p.id] = p
    return registry
