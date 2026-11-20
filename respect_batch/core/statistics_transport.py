# Pinned public HTTPS transport, copied from Studio provider probes.
import http.client
import ipaddress
import json
import socket
import ssl
import time

import requests

from . import distribution, network


def public_ip(value):
    ip = ipaddress.ip_address(value)
    if getattr(ip, 'ipv4_mapped', None):
        ip = ip.ipv4_mapped
    return ip.is_global and not (ip.is_multicast or ip.is_unspecified or ip.is_reserved)


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        deadline = time.monotonic() + self.timeout
        raw = socket.create_connection((self.address, 443), self.timeout)
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            raw.settimeout(remaining)
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def _proxied_json(url, proxy, max_bytes):
    """Only fixed public statistics URLs; no account credentials or redirects."""
    started = time.monotonic()
    with requests.Session() as session:
        session.trust_env = False  # no .netrc credentials for public statistics
        with session.get(url, proxies={'http': proxy, 'https': proxy},
                         headers={'Accept': 'application/json', 'Accept-Encoding': 'identity'},
                         timeout=(8, 2), stream=True, allow_redirects=False, verify=True) as response:
            if response.status_code != 200:
                raise ValueError('HTTP ' + str(response.status_code))
            chunks, size = [], 0
            while True:
                if time.monotonic() - started >= 12:
                    raise TimeoutError()
                # read1 performs at most one socket read; a stalled read times out
                # after 2 seconds, including a drip-feed near the overall deadline.
                chunk = response.raw.read1(min(65536, max_bytes + 1 - size), decode_content=False)
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError('response too large')
            return json.loads(b''.join(chunks))


def get_json(url):
    """Use local network preferences without changing Studio's shared normalizers."""
    from . import supplier_statistics as supplier
    allowed = {base + path for base, path, _ in supplier.SOURCES.values()}
    allowed.add(supplier.SOURCES['zhongheng'][0] + '/api/models')
    if url not in allowed:
        raise ValueError('invalid statistics URL')
    if distribution.ENABLED and getattr(distribution, 'MANAGED', False):
        proxy = network.proxy_for_url(url)
        if proxy:
            return _proxied_json(url, proxy, supplier.MAX_BYTES)
    return supplier.get_json(url)
