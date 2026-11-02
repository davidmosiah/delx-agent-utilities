"""One HTTP hop over validated numeric sockets. No environment proxy support."""
from __future__ import annotations

import http.client
import os
import ssl
import time
from urllib.parse import quote, urlsplit

from ._public_socket import _connect_public


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def connect(self) -> None:
        self.sock = _connect_public(self.host, self.port, self.timeout)


class _PinnedHTTPSConnection(_PinnedHTTPConnection):
    default_port = 443

    def connect(self) -> None:
        raw = _connect_public(self.host, self.port, self.timeout)
        try:
            # Keep the original DNS identity for SNI AND certificate validation.
            context = ssl.create_default_context()
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            self.sock = context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def _request_public_http(url: str, *, timeout: float, method: str,
                         max_bytes: int = 8 * 1024 * 1024):
    """Return (status, bytes, headers, reason) without following any redirect.

    Direct egress only: fails closed on configured relevant proxy variables.
    OS DNS resolution may block beyond timeout; subsequent operations use a
    remaining budget. A timeout/byte limit is not a concurrency/resource quota.
    """
    if any(ord(c) < 32 or ord(c) == 127 for c in url):
        raise ValueError('blocked: control characters in HTTP URL')
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('blocked: only HTTP(S) URLs with hosts are allowed')
    # Do not silently bypass an operator's proxy/egress policy. NO_PROXY is not
    # interpreted: bypass semantics need explicit operator-authorized design.
    proxy_keys = ('ALL_PROXY', 'all_proxy',
                  'HTTPS_PROXY', 'https_proxy') if parsed.scheme == 'https' else (
                  'ALL_PROXY', 'all_proxy', 'HTTP_PROXY', 'http_proxy')
    if any(os.environ.get(key, '').strip() for key in proxy_keys):
        # Never interpolate values: proxy URLs may contain credentials.
        raise ValueError('blocked: configured proxy is unsupported by the pinned direct HTTP transport')
    if parsed.username is not None or parsed.password is not None:
        raise ValueError('blocked: URL credentials are not supported')
    host = parsed.hostname
    if '%' in host:
        raise ValueError('blocked: percent-encoded/scoped URL hosts are not allowed')
    host = host.encode('idna').decode('ascii').rstrip('.')
    port = parsed.port if parsed.port is not None else (443 if parsed.scheme == 'https' else 80)
    if not host or not 1 <= port <= 65535:
        raise ValueError('blocked: invalid HTTP host or port')
    method = method.upper()
    if method not in ('GET', 'HEAD'):
        raise ValueError('only GET and HEAD are supported')
    # Preserve existing percent escapes; encode Unicode without double-encoding.
    target = quote(parsed.path or '/', safe="/%:@!$&'()*+,;=-._~")
    if parsed.query:
        target += '?' + quote(parsed.query, safe="/%?:@!$&'()*+,;=-._~")
    authority = f'[{host}]' if ':' in host else host
    default_port = 443 if parsed.scheme == 'https' else 80
    if port != default_port:
        authority += f':{port}'
    connection_type = _PinnedHTTPSConnection if parsed.scheme == 'https' else _PinnedHTTPConnection
    connection = connection_type(host, port, timeout=timeout)
    deadline = time.monotonic() + timeout
    try:
        connection.connect()
        def remaining():
            value = deadline - time.monotonic()
            if value <= 0:
                raise TimeoutError('HTTP request timed out')
            if connection.sock is not None:
                connection.sock.settimeout(value)
        remaining()
        connection.request(method, target, headers={
            'Host': authority,
            'User-Agent': 'DelxAgentToolkit/3.3',
            'Accept-Encoding': 'identity',
            'Connection': 'close',
        })
        remaining()
        response = connection.getresponse()
        try:
            if method == 'HEAD':
                raw = b''
            else:
                # Servers should honor identity negotiation. Never decompress
                # an unbounded response or silently return compressed garbage.
                encoding = response.headers.get('content-encoding', '').strip().lower()
                if encoding not in ('', 'identity'):
                    raise ValueError('unsupported HTTP content encoding (identity required)')
                chunks = []
                total = 0
                while True:
                    remaining()
                    # read1 yields after one buffered/socket read, so the total
                    # elapsed budget can be checked between trickled chunks.
                    chunk = response.read1(min(65536, max_bytes + 1 - total))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(f'HTTP response exceeds {max_bytes} bytes')
                    chunks.append(chunk)
                raw = b''.join(chunks)
            return response.status, raw, response.headers, response.reason
        finally:
            response.close()
    finally:
        connection.close()
