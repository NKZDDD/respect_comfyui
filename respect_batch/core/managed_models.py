"""Turn server Key bindings into a private route map and a public model catalogue."""
import copy
import hashlib
from urllib.parse import urlsplit

from . import config, model_catalog, providers

KEY_FIELDS = ('api_key', 'image_1k_api_key', 'image_4k_api_key', 'video_api_key')


def build(owner, configs, storage):
    from .release import OPTION_KEYS
    if not isinstance(configs, dict) or len(configs) > 48:
        raise ValueError('后台配置格式无效')
    cfg = copy.deepcopy(config.DEFAULTS)
    cfg['upload'] = dict(storage or {}, backend='managed', mode='when_required', owner=owner,
                         enabled=bool((storage or {}).get('assigned') and (storage or {}).get('available')))
    profile = dict(preview=False, managed=True, models=[], config=cfg, private_names=[], issues=[])
    known = set()
    for pid, group in configs.items():
        if pid == 'prompt_rewrite_llm':
            continue
        if not isinstance(group, dict):
            raise ValueError('后台服务商配置无效')
        rows = group.get('keys', [group])
        if not isinstance(rows, list) or len(rows) > 32:
            raise ValueError('后台 Key 列表无效')
        cls = providers.REGISTRY.get(pid)
        if cls is None:
            if rows:
                profile['issues'].append('有已分配服务尚未适配此批量版，请联系管理员更新客户端')
            continue
        cap = cls().capabilities()
        for row in rows:
            if not isinstance(row, dict) or any(not isinstance(row.get(k, ''), str)
                    for k in (*KEY_FIELDS, 'base_url', 'key_id', 'key_name', 'assignment_id')):
                raise ValueError('后台 Key 配置无效')
            url = row.get('base_url') or cls.default_base_url
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError('后台服务地址必须为 HTTPS，请联系管理员')
            label = row.get('key_name') or '已授权服务'
            bound = row.get('models', [])
            if not isinstance(bound, list) or any(not isinstance(m, str) or not m for m in bound):
                raise ValueError('后台模型绑定格式无效')
            for field in KEY_FIELDS:
                if not row.get(field):
                    continue
                pc = dict(api_key=row[field], base_url=url, proxy='direct')
                # Model bindings take precedence over unfiltered provider catalogues.
                result = {'ok': True, 'rows': [{'id': m} for m in bound]} if bound else model_catalog.fetch(pid, pc)
                if not result.get('ok'):
                    profile['issues'].append(label + '：模型读取失败，请在后台绑定模型后刷新')
                    continue
                resolved_cap = model_catalog.apply_catalog(cap, result, '后台 Key')
                for info in result.get('rows', []):
                    model = info['id']
                    kinds = model_catalog.model_kind(info, cap)
                    if not kinds:
                        profile['issues'].append(label + '：有模型类型无法识别，请更新客户端适配')
                    for kind in kinds:
                        if kind not in cls.supports or kind not in ('image', 'video'):
                            continue
                        if (field.startswith('image_') and kind != 'image') or (field == 'video_api_key' and kind != 'video'):
                            continue
                        # Multiple split credential fields must stay individually attributable.
                        variant = field if field != 'api_key' else ''
                        identity = (pid, kind, model, variant)
                        if identity in known:
                            continue  # The first authorized Key wins for overlapping models.
                        block = resolved_cap.get(kind, {})
                        opts = {**block, **block.get('model_options', {}).get(model, {})}
                        opts = {k: copy.deepcopy(v) for k, v in opts.items() if k in OPTION_KEYS}
                        inst = cls()
                        opts['ref_mode'] = 'url' if inst.needs_url(model, kind) else inst.ref_mode
                        if field == 'image_1k_api_key':
                            opts['resolutions'] = ['1K']
                        for default, choices in (('default_size', 'sizes'), ('default_ratio', 'ratios'), ('default_duration', 'durations')):
                            if opts.get(choices) and opts.get(default) not in opts[choices]:
                                opts[default] = opts[choices][0]
                        # Optional maximums in adapters may be absent; absence means no local cap.
                        opts.setdefault('max_refs', None)
                        route = copy.deepcopy(pc)
                        route['_usage'] = {k: row.get(k, '') for k in ('key_id', 'key_name', 'assignment_id')}
                        route['_usage']['owner'] = owner
                        suffix = {'image_1k_api_key': ' · 1K Key', 'image_4k_api_key': ' · 4K Key', 'video_api_key': ' · 视频 Key'}.get(field, '')
                        profile['models'].append(dict(id='m' + hashlib.sha256(repr(identity).encode()).hexdigest()[:24],
                            label=f'{label} · {model}{suffix}', provider=pid, kind=kind, model=model, options=opts, route=route))
                        cfg['providers'].setdefault(pid, copy.deepcopy(route))
                        known.add(identity)
    profile['issues'] = list(dict.fromkeys(profile['issues']))
    return profile
