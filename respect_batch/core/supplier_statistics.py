"""Supplier-published model statistics. No generation calls or customer usage data.

Shared by the desktop backend and auth service. Requests only read a bounded
cache; two daemon workers fetch fixed public HTTPS endpoints outside all locks.
"""
import copy
from datetime import datetime
import json
import math
import queue
import socket
import threading
import time
from urllib.parse import urlsplit

import certifi

from .statistics_transport import PinnedHTTPS, public_ip

TTL = 300
STALE_AFTER = 900
MAX_BYTES = 2 * 1024 * 1024
MAX_MODELS = 5000
SOURCES = {
    'zhongheng': ('https://www.yeepay.top', '/api/model-stats', 'task'),
    'ake': ('https://snumom.com', '/api/model_status', 'task'),
    'wuxianhuabu': ('https://videogogo.top', '/api/model-plaza/v1/models', 'task'),
    'cangyuan': ('https://ai.cangyuansuanli.cn', '/api/pricing/video-history', 'task'),
    'octopus': ('https://zexapi.com', '/agent-api/v1/public/model-status', 'task'),
    'julun': ('https://julun.cc', '/api/perf-metrics/summary?hours=24', 'request'),
    'kunji': ('https://img.yunfei.best', '/api/perf-metrics/summary?hours=24', 'request'),
    'zeroapi': ('https://zeroapi.ai-ren.cn', '/api/perf-metrics/summary?hours=24', 'request'),
    'xiaobalong': ('https://api.keik.cc', '/api/perf-metrics/summary?hours=24', 'request'),
    'valeclouds': ('https://valeclouds.com', '/api/perf-metrics/summary?hours=24', 'request'),
}
ALIASES = {'cangyuan_video': 'cangyuan'}


def source_id(provider):
    return ALIASES.get(provider, provider)


def matches(provider, base_url):
    """Never attribute another/custom gateway's results to a known supplier."""
    pid = source_id(provider)
    if pid not in SOURCES:
        return False
    if not base_url:
        return True
    try:
        u = urlsplit(base_url)
        hosts = {urlsplit(SOURCES[pid][0]).hostname}
        if pid == 'zhongheng':
            hosts.add('cnd-coo-new.pages.dev')  # supplier's announced migration
        return u.scheme == 'https' and u.hostname in hosts and u.port in (None, 443) and not u.username
    except ValueError:
        return False


def number(value, *, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0 or (maximum is not None and value > maximum):
        return None
    return value


def count(value):
    value = number(value)
    return int(value) if value is not None and value == int(value) else None


def timestamp(value):
    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp())
        except (ValueError, OverflowError):
            return 0
    return count(value) or 0


def row(model, rate=None, *, samples=None, seconds=None, window='', basis='', variant=''):
    if not isinstance(model, str) or not model.strip() or len(model) > 300:
        raise ValueError('invalid model')
    samples = count(samples)
    rate = number(rate, maximum=100) if samples != 0 else None
    seconds = number(seconds)
    return dict(model=model, rate=round(rate, 2) if rate is not None else None,
                samples=samples, seconds=round(seconds, 2) if seconds else None,
                window=window, basis=basis, variant=str(variant)[:150])


def percentage(success, total):
    success, total = count(success), count(total)
    if total and success is not None and success <= total:
        return 100 * success / total
    return None


def normalize(pid, payload, catalog=None):
    """Keep full model IDs and supplier scopes. Never synthesize/pad samples."""
    if not isinstance(payload, dict) or payload.get('success') is False or payload.get('error'):
        raise ValueError('invalid response')
    data = payload['data']
    rows, source_at = [], 0
    if pid == 'zhongheng':
        names = {str(m['id']): m['public_name'] for m in catalog['data']}
        source_at = timestamp(payload.get('generated_at'))
        for m in data:
            name = names.get(str(m['model_id']))
            if name:
                rows.append(row(name, m.get('success_rate'), samples=m.get('completed_count'),
                                seconds=m.get('average_duration_seconds'), window='近 24 小时',
                                basis='服务商终态统计；平均耗时含排队，仅计成功任务'))
    elif pid == 'ake':
        source_at = timestamp(payload.get('updated_at'))
        if payload.get('available') is False:
            raise ValueError('statistics unavailable')
        for name, m in data.items():
            rows.append(row(name, m.get('success_rate'), samples=m.get('total'), seconds=m.get('avg_latency_s'),
                            window='近 7 天 / 最近 100 次', basis='服务商公布比率；不足样本可能补齐展示，保留其原值'))
    elif pid == 'wuxianhuabu':
        for m in data:
            perf = m.get('recent_performance') or {}
            rows.append(row(m['display_name'], percentage(perf.get('success_count'), perf.get('sample_size')),
                            samples=perf.get('sample_size'), seconds=perf.get('average_duration_seconds'),
                            window='最近最多 100 条终态', variant=m.get('group_name', ''),
                            basis='服务商样本换算；取消除外，平均耗时含排队，仅计成功任务'))
    elif pid == 'cangyuan':
        if data.get('ready') is not True:
            raise ValueError('statistics updating')
        source_at = timestamp(data.get('generated_at'))
        for name, m in data['models'].items():
            tasks = m['tasks']
            if not isinstance(tasks, list) or len(tasks) > 20 or any(t.get('status') not in ('SUCCESS', 'FAILURE', 'REJECTED') for t in tasks):
                raise ValueError('invalid task samples')
            ms = number(m.get('average_ms'))
            rows.append(row(name, percentage(sum(t['status'] == 'SUCCESS' for t in tasks), len(tasks)),
                            samples=len(tasks), seconds=ms / 1000 if ms is not None else None,
                            window='最近最多 20 条任务', basis='服务商样本换算；审核拒绝计入分母，平均耗时仅计有耗时样本'))
    elif pid == 'octopus':
        for m in data['models']:
            samples = m['samples']
            if not isinstance(samples, list) or len(samples) > 100 or any(s.get('status') not in ('success', 'failure', 'user_issue') for s in samples):
                raise ValueError('invalid task samples')
            valid = [s for s in samples if s['status'] != 'user_issue']
            rows.append(row(m['model_name'], percentage(sum(s['status'] == 'success' for s in valid), len(valid)),
                            samples=len(valid), window='最近最多 100 条样本',
                            basis='服务商真实样本换算；按官网口径排除用户问题，不补齐模拟样本'))
    else:
        for m in data['models']:
            ms = number(m.get('avg_latency_ms'))
            rows.append(row(m['model_name'], m.get('success_rate') if m.get('has_data') is not False else None,
                            samples=m.get('request_count'), seconds=ms / 1000 if ms is not None else None,
                            window='近 24 小时', basis='服务商请求统计；是否等同视频最终成片口径尚未确认'))
    if len(rows) > MAX_MODELS:
        raise ValueError('too many models')
    return dict(models=rows, source_at=source_at, scope=SOURCES[pid][2])


def get_json(url):
    """Fixed public targets, no Key/cookies/proxy/redirect, bounded body and time."""
    u = urlsplit(url)
    started, conn = time.monotonic(), None
    addresses = list(dict.fromkeys(x[4][0] for x in socket.getaddrinfo(u.hostname, 443, type=socket.SOCK_STREAM)))
    if not addresses or any(not public_ip(a) for a in addresses):
        raise ValueError('invalid address')
    try:
        conn = PinnedHTTPS(u.hostname, addresses[0], 8)
        # Include Mozilla roots on Windows hosts with an incomplete OS trust store.
        # Keep hostname/certificate verification enabled.
        conn._context.load_verify_locations(certifi.where())
        conn.request('GET', u.path + ('?' + u.query if u.query else ''),
                     headers={'Accept': 'application/json', 'Accept-Encoding': 'identity',
                              'User-Agent': 'Respect-Studio-Model-Statistics/1'})
        response = conn.getresponse()
        if response.status != 200:
            raise ValueError('HTTP ' + str(response.status))
        chunks, size = [], 0
        while True:
            remaining = 12 - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError()
            if conn.sock:
                conn.sock.settimeout(remaining)
            chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError('response too large')
        return json.loads(b''.join(chunks))
    finally:
        if conn:
            conn.close()


def fetch(pid):
    base, path, _ = SOURCES[pid]
    data = get_json(base + path)
    catalog = get_json(base + '/api/models') if pid == 'zhongheng' else None
    return normalize(pid, data, catalog)


class StatisticsCache:
    def __init__(self, fetcher=fetch, clock=time.time):
        self.fetcher, self.clock = fetcher, clock
        self.lock = threading.Lock()
        self.entries, self.pending, self.next_at = {}, set(), {}
        self.queue = queue.Queue(maxsize=len(SOURCES))
        self.stop = threading.Event()
        self.threads = []

    def snapshot(self, provider, base_url=''):
        pid, now = source_id(provider), self.clock()
        if not matches(pid, base_url):
            return dict(provider=provider, state='unsupported', models=[], refreshing=False,
                        message='暂无匹配此服务商地址的公开统计')
        with self.lock:
            if not self.threads and not self.stop.is_set():
                self.threads = [threading.Thread(target=self.work, name=f'model-statistics-{i}', daemon=True) for i in range(2)]
                for thread in self.threads:
                    thread.start()
            if not self.stop.is_set() and pid not in self.pending and now >= self.next_at.get(pid, 0):
                self.pending.add(pid)
                self.next_at[pid] = now + TTL
                self.queue.put_nowait(pid)
            value = copy.deepcopy(self.entries.get(pid, dict(state='loading', models=[], fetched_at=0)))
            value.update(provider=provider, refreshing=pid in self.pending)
        age = now - (value.get('source_at') or value.get('fetched_at') or 0)
        value['stale'] = bool(value.get('fetched_at') and (age > STALE_AFTER or value.get('error')))
        return value

    def work(self):
        while not self.stop.is_set():
            try:
                pid = self.queue.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                data = self.fetcher(pid)
                now = int(self.clock())
                if data.get('source_at', 0) > now + 300:
                    raise ValueError('invalid timestamp')
                value = dict(data, state='ready' if data['models'] else 'empty', fetched_at=now, error='')
                with self.lock:
                    self.entries[pid] = value
            except Exception:
                # Don't expose response bodies, routes, or exception messages to clients.
                with self.lock:
                    previous = self.entries.get(pid, dict(models=[], fetched_at=0))
                    self.entries[pid] = dict(previous, state='error', error='服务商统计暂不可用')
            finally:
                with self.lock:
                    self.pending.discard(pid)
                self.queue.task_done()

    def close(self):
        self.stop.set()


CACHE = StatisticsCache()
