"""Local connection policy for the managed batch client, including downloaded adapters."""
from functools import wraps
import os
from urllib.parse import urlsplit

import requests

from . import distribution, paths
from .store import read_json, write_json

DEFAULTS = {'mode': 'system', 'proxy_url': ''}


def validate(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError('联网设置格式无效')
    mode, address = value.get('mode', 'system'), value.get('proxy_url', '')
    if mode not in ('system', 'direct', 'custom') or not isinstance(address, str):
        raise ValueError('请选择跟随系统代理、直连或指定代理地址')
    address = address.strip()
    if mode != 'custom':
        return dict(mode=mode, proxy_url='')
    try:
        parsed = urlsplit(address)
        valid = (len(address) <= 2048 and not any(c.isspace() for c in address)
                 and parsed.scheme in ('http', 'https') and parsed.hostname and parsed.port
                 and parsed.username is None and parsed.password is None
                 and parsed.path in ('', '/') and not parsed.query and not parsed.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError('请填写带端口的 HTTP/HTTPS 代理地址，例如 http://127.0.0.1:7890；不接受账号密码、路径或查询参数')
    return dict(mode=mode, proxy_url=address.rstrip('/'))


def load():
    return validate(read_json(os.path.join(paths.data_dir(), 'network.json'), DEFAULTS))


def save(value):
    value = validate(value)
    # Only validated local preferences; upstream URL/Key redaction must not alter
    # the user's proxy address. No credentials or arbitrary fields are accepted.
    write_json(os.path.join(paths.data_dir(), 'network.json'), value, redact_output=False)
    return value


def proxy_value():
    value = load()
    return {'system': '', 'direct': 'direct', 'custom': value['proxy_url']}[value['mode']]


def proxy_for_url(url):
    value = load()
    if value['mode'] == 'direct':
        return None
    if value['mode'] == 'custom':
        return value['proxy_url']
    # Requests reads environment proxies and Windows manual proxy settings here,
    # including their bypass rules. PAC scripts are not evaluated by Requests.
    return requests.utils.select_proxy(url, requests.utils.get_environ_proxies(url))


def install():
    """Resolve proxies at request time; do not alter headers, bodies, TLS or retries.

    Adapters can create their own Session or pass explicit direct proxies. Applying
    the policy at Requests' merge boundary covers those too, only in managed mode.
    """
    original = requests.sessions.Session.merge_environment_settings
    if getattr(original, '_respect_batch_network', False):
        return
    original_rebuild = requests.sessions.Session.rebuild_proxies

    def proxies_for(url):
        selected = proxy_for_url(url) or ''
        return {'http': selected, 'https': selected, 'all': ''}

    @wraps(original)
    def merge(session, url, proxies, stream, verify, cert):
        settings = original(session, url, proxies, stream, verify, cert)
        if distribution.ENABLED and getattr(distribution, 'MANAGED', False):
            # Replace after merging, so a stale Session proxy or a host-specific
            # environment proxy cannot override the selected mode.
            settings['proxies'] = proxies_for(url)
        return settings

    @wraps(original_rebuild)
    def rebuild(session, request, proxies):
        if distribution.ENABLED and getattr(distribution, 'MANAGED', False):
            proxies = proxies_for(request.url)
        return original_rebuild(session, request, proxies)

    merge._respect_batch_network = True
    requests.sessions.Session.merge_environment_settings = merge
    requests.sessions.Session.rebuild_proxies = rebuild
