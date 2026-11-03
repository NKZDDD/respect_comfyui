"""自用版模型目录：按服务商刷新、按凭据隔离缓存；不将清单当作生成测试。"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
from datetime import datetime, timezone

import requests

from . import config, paths, providers
from .store import read_json, write_json

_LOCK = threading.RLock()


def identity(pid, pc):
    values = [pid, pc.get('base_url') or providers.REGISTRY[pid].default_base_url,
              pc.get('api_key', '')]
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def fetch(pid, pc):
    """仅 GET 模型端点；不跟随跨站跳转、不返回含凭据的原始错误。"""
    from . import distribution
    if distribution.ENABLED and getattr(distribution, 'MANAGED', False):
        # Discovery is part of the downloaded adapter too: do not assume that
        # every new provider exposes /v1/models or the same response schema.
        try:
            prov = providers.build(pid, pc.get('api_key', ''), pc.get('base_url', ''), 'direct', 20)
            reader = getattr(prov, 'catalog_rows', prov.list_models)
            rows = reader()
            if not isinstance(rows, list):
                raise ValueError()
            rows = [dict(r) if isinstance(r, dict) else {'id': r} for r in rows]
            rows = [r for r in rows if isinstance(r.get('id'), str) and r['id']]
            return {'ok': bool(rows), 'rows': rows, 'models': [r['id'] for r in rows]}
        except Exception:
            return {'ok': False, 'msg': '适配包模型清单读取失败，请在后台绑定模型后刷新'}
    if pid == 'hvtald':
        return {'ok': False, 'msg': '该服务商使用固定账号模型，没有模型清单接口'}
    prov = providers.build(pid, pc.get('api_key', ''), pc.get('base_url', ''),
                           pc.get('proxy') or 'direct', 20)
    endpoint = {'gate': '/public/model_group/info',
                'zhi': '/api/v1/available-models'}.get(pid, '/v1/models')
    if not prov.session.base_url:
        return {'ok': False, 'msg': '请先填写该服务商的接口地址'}
    keys = [prov.session.api_key]
    if pid == 'kunji':
        keys = list(dict.fromkeys(prov.keys.values())) or keys
    rows, failures = {}, []
    for key in keys:
        prov.session.api_key = key
        try:
            with requests.Session() as session:
                session.trust_env = False
                response = session.get(prov.session.base_url + endpoint,
                    headers=prov.session._headers(), proxies=prov.session._proxies(),
                    timeout=(8, 20), allow_redirects=False)
            if response.status_code != 200:
                failures.append(f'HTTP {response.status_code}'); continue
            data = response.json()
            data = data if isinstance(data, list) else data.get('data')
            if not isinstance(data, list):
                failures.append('接口未返回模型数组'); continue
            for row in data:
                if not isinstance(row, dict):
                    continue
                mid = row.get('model_group') if pid == 'gate' else row.get('id')
                if mid is None or not str(mid).strip():
                    continue
                mid = str(mid).strip()
                # 只保留模型字段，不把响应中的账号、调试信息打包或传给页面。
                item = {'id': mid}
                for field in ('type', 'model_type', 'category', 'output_modalities',
                              'display_name', 'durations_seconds', 'ratios',
                              'max_images', 'resolution'):
                    if field in row:
                        item[field] = row[field]
                rows[mid] = item
        except requests.RequestException:
            failures.append('网络连接失败或超时')
        except (ValueError, AttributeError):
            failures.append('接口返回的不是模型 JSON')
    if not rows:
        return {'ok': False, 'msg': '；'.join(dict.fromkeys(failures)) or '模型清单为空'}
    return {'ok': True, 'models': sorted(rows), 'rows': [rows[k] for k in sorted(rows)],
            'updated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'partial': bool(failures),
            'msg': '部分分组拉取失败，已合并成功分组' if failures else '模型清单已更新'}


def model_kind(row, cap):
    mid = row['id']
    known = [k for k in cap.get('supports', []) if mid in cap.get(k, {}).get('models', [])]
    if known:
        return known
    metadata = ' '.join(str(row.get(k, '')) for k in
                        ('type', 'model_type', 'category', 'output_modalities')).lower()
    kinds = [k for k in ('image', 'video') if k in metadata]
    if kinds:
        return kinds
    name = mid.lower()
    if re.search(r'image|banana|seedream|flux|dall|gpt本地|香蕉|绘图|生图|图片', name):
        return ['image']
    if re.search(r'video|seedance|sora|veo|kling|h3|wan|happy.?horse|omni_flash|快乐马|可灵|视频|sd[\d.-]|官方稳定版.*2\.5', name):
        return ['video']
    if re.search(r'^gpt-|^o[134]-|claude|deepseek|qwen|embedding|rerank|whisper|tts|gemini|^glm-|^kimi-|doubao-seed|推理', name):
        return ['other']
    return []


def _from_schema(schema):
    """`capability_schema` → 我们的 model_options 形状。

    无限画布那家逐模型回一份这个，比文档准 —— 而**同一个平台里字段名都不统一**：
    `seedance-2.5-hf-720p` 用 `aspect_ratio`（单数），别的用 `aspect_ratios`
    （复数）。只认一种的话有的模型的比例会整份丢掉，然后前端给的候选是整家的
    并集 —— 人选到一个这个模型不收的值，要到付费请求发出去才收到拒绝。

    **只取声明了的**，没声明的键不放进来 —— 放一个「看起来合理」的数
    和照文档抄没有区别：它会显示在页面上、会拿去拦人，而没有任何东西背书。
    """
    if not isinstance(schema, dict):
        return {}
    out = {}
    # Duration declarations remain useful hints after refresh, never limits.
    dur = schema.get('duration')
    if isinstance(dur, dict):
        if isinstance(dur.get('values'), list) and dur['values']:
            out['durations'] = [int(x) for x in dur['values']]
        elif isinstance(dur.get('min'), int) and isinstance(dur.get('max'), int):
            out['durations'] = list(range(dur['min'], dur['max'] + 1))
    if 'durations' not in out and isinstance(schema.get('durations'), list) and schema['durations']:
        out['durations'] = [int(x) for x in schema['durations']]
    for key in ('aspect_ratios', 'aspect_ratio'):        # 单复数都认
        v = schema.get(key)
        if isinstance(v, list) and v:
            out['ratios'] = [str(x) for x in v]
            break
    v = schema.get('resolutions')
    if isinstance(v, list) and v:
        out['resolutions'] = [str(x) for x in v]
    for key, target in (('max_reference_images', 'max_refs'),
                        ('max_reference_videos', 'max_video_refs'),
                        ('max_reference_audios', 'max_audio_refs'),
                        ('max_reference_assets', 'max_asset_refs'),
                        ('min_reference_images', 'min_refs'),
                        ('max_prompt_chars', 'max_prompt_chars')):
        if isinstance(schema.get(key), int):
            out[target] = schema[key]
    # 无限画布当前目录使用短字段名；0 是明确不支持，不能当成缺省丢掉。
    for key, target in (('max_images', 'max_refs'), ('max_videos', 'max_video_refs'),
                        ('max_audios', 'max_audio_refs')):
        if target not in out and isinstance(schema.get(key), int):
            out[target] = schema[key]
    # 「这个模型收不收视频参考」也是它自己声明的。**只在明确写了 False
    # 时记 0** —— 没写就是没声明，不是不允许（见 `_UNKNOWN` 那一课）。
    if schema.get('videoReference') is False:
        out['max_video_refs'] = 0
    kinds = schema.get('reference_types')
    if isinstance(kinds, list) and kinds:
        up = {str(x).upper() for x in kinds}
        for word, target in (('VIDEO', 'max_video_refs'),
                             ('AUDIO', 'max_audio_refs')):
            if word not in up:
                out[target] = 0
    return out


def _from_toplevel(row):
    """超模那套：逐模型的约束摆在**顶层**，不在 capability_schema 里。

    字段名和别家都不一样（`supported_aspect_ratios` / `max_reference_images` /
    `n_max` / `supported_quality_values` / `resolution_mode`），所以单独一支。

    **只取声明了的。** 超模的 `gpt-image2-*-Native` 把 `max_reference_images`
    写成 null（明确表示没声明），那就不给它填数 —— 填一个「看起来合理」的
    和照文档抄没有区别：它会显示在页面上、会拿去拦人，而没有任何东西背书。
    """
    if not isinstance(row, dict):
        return {}
    out = {}
    v = row.get('supported_aspect_ratios')
    if isinstance(v, list) and v:
        out['ratios'] = [str(x) for x in v]
    v = row.get('supported_image_sizes') or row.get('resolution_mode')
    if isinstance(v, str) and v:
        out['resolutions'] = [s.strip() for s in v.split('/') if s.strip()]
    elif isinstance(v, list) and v:
        out['resolutions'] = [str(x) for x in v]
    for key, target in (('max_reference_images', 'max_refs'),
                        ('n_max', 'n_max')):
        if isinstance(row.get(key), int):          # null / None 不算声明
            out[target] = row[key]
    v = row.get('supported_quality_values')
    if isinstance(v, list) and v:
        out['quality'] = [str(x) for x in v]
    return out


def apply_catalog(cap, result, source):
    cap = copy.deepcopy(cap)
    rows = result.get('rows') or [{'id': m} for m in result.get('models', [])]
    grouped = {k: [] for k in cap.get('supports', [])}
    unknown, other = [], []
    for row in rows:
        kinds = model_kind(row, cap)
        if not kinds:
            unknown.append(row['id'])
        elif not any(k in grouped for k in kinds):
            other.append(row['id'])
        for kind in kinds:
            if kind in grouped:
                grouped[kind].append(row['id'])
    for kind, names in grouped.items():
        block = cap[kind]
        block['models'] = names + unknown
        if block.get('default_model') not in block['models']:
            block['default_model'] = next(iter(block['models']), '')
        for row in rows:
            if row['id'] not in names:
                continue
            options = {}
            for field, target in [('durations_seconds', 'durations'), ('ratios', 'ratios')]:
                if isinstance(row.get(field), list) and row[field]:
                    options[target] = row[field]
            if isinstance(row.get('max_images'), int):
                options['max_refs'] = row['max_images']
            options.update(_from_schema(row.get('capability_schema')))
            options.update(_from_toplevel(row))
            if isinstance(options.get('max_refs'), int) and not block.get('refs_unlimited'):
                options['refs_unlimited'] = False
            pattern = block.get('unlimited_ref_model_pattern')
            if pattern and re.search(pattern, row['id']):
                options.update(refs_unlimited=True, max_refs=None)
            if block.get('refs_unlimited'):
                # 这一类服务商声明了「参考图张数本地不限制」：清单里的数只是参考，
                # 合并进来就又会按它拦、按它截断。
                options.pop('max_refs', None)
            if options:
                block.setdefault('model_options', {}).setdefault(row['id'], {}).update(options)
    cap['model_catalog'] = {'source': source, 'updated_at': result.get('updated_at', ''),
        'total': len(rows), 'unknown': unknown, 'other': other,
        'all_models': [r['id'] for r in rows], 'partial': result.get('partial', False)}
    return cap


def capabilities(cfg):
    caps = providers.list_capabilities()
    saved = read_json(paths.res('model-snapshot.json'), {}) or {}
    cache = read_json(paths.data_dir() + '/model-catalog.json', {}) or {}
    for i, cap in enumerate(caps):
        pid = cap['id']
        pc = config.provider_cfg(cfg, pid)
        current = cache.get(pid, {})
        if current.get('identity') == identity(pid, pc) and current.get('ok'):
            caps[i] = apply_catalog(cap, current, '当前 Key 拉取')
        elif saved.get(pid, {}).get('ok'):
            caps[i] = apply_catalog(cap, saved[pid], '打包时快照，请按当前 Key 刷新')
    return caps


def refresh(pid, cfg):
    pid = providers.resolve_id(pid)
    pc = config.provider_cfg(cfg, pid)
    result = fetch(pid, pc)
    if result['ok']:
        with _LOCK:
            path = paths.data_dir() + '/model-catalog.json'
            cached = read_json(path, {}) or {}
            cached[pid] = {**result, 'identity': identity(pid, pc)}
            write_json(path, cached)
        result['capability'] = next(c for c in capabilities(cfg) if c['id'] == pid)
    return result
