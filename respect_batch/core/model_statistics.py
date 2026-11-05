"""Join public supplier statistics to the account's exact, private model routes."""
from . import providers, release
from .supplier_statistics import CACHE


def snapshot():
    result, sources = [], {}
    # The route catalogue already applies Key bindings, first-Key precedence and
    # image/video permissions. Never use the supplier-wide catalogue for choices.
    for item in release.catalog():
        pid = item['provider']
        cls = providers.REGISTRY.get(pid)
        base = (item.get('route') or {}).get('base_url') or getattr(cls, 'default_base_url', '')
        identity = (pid, base)
        if identity not in sources:
            sources[identity] = CACHE.snapshot(pid, base)
        data = sources[identity]
        stats = [{k: r.get(k) for k in ('rate', 'samples', 'seconds', 'window', 'basis', 'variant')}
                 for r in data.get('models', []) if r.get('model') == item['model']]
        result.append(dict(id=item['id'], model_id=item['model'], kind=item['kind'],
                           stats=stats, state=data['state'], stale=bool(data.get('stale')),
                           fetched_at=data.get('fetched_at', 0), source_at=data.get('source_at', 0)))
    return dict(ok=True, models=result)
