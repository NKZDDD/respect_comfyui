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
