"""Direct TCP connections pinned to one validated DNS answer set (no proxies)."""
from __future__ import annotations

import ipaddress
import socket
import time


def _public_address(value: str) -> bool:
    # Scoped addresses and IPv6 transition mechanisms are deliberately excluded.
    if '%' in value:
        return False
    ip = ipaddress.ip_address(value)
    if isinstance(ip, ipaddress.IPv6Address):
        # Translation prefixes can encode private IPv4 destinations even when
        # older Python ipaddress versions classify the IPv6 value as global.
        if ip in ipaddress.IPv6Network('64:ff9b::/96') or ip in ipaddress.IPv6Network('64:ff9b:1::/48'):
            return False
        if ip.ipv4_mapped is not None:
            return _public_address(str(ip.ipv4_mapped))
        if ip.sixtofour is not None or ip.teredo is not None:
            return False
    return ip.is_global and not (ip.is_multicast or ip.is_reserved or ip.is_unspecified)


def _connect_public(host: str, port: int, timeout: float) -> socket.socket:
    """Resolve once, validate ALL answers, then connect numeric sockaddrs only.

    Caller owns the returned socket. DNS resolution uses the OS resolver and is
    not interruptible by the socket timeout; no second hostname lookup occurs.
    """
    if not host or '%' in host or any(ord(c) < 33 or ord(c) == 127 for c in host):
        raise ValueError('blocked: invalid network host')
    if not 1 <= port <= 65535:
        raise ValueError('blocked: invalid network port')
    host = host.encode('idna').decode('ascii').rstrip('.')
    if host.lower() == 'localhost' or host.lower().endswith(('.localhost', '.local')):
        raise ValueError('blocked: local network targets are not allowed')
    deadline = time.monotonic() + timeout
    answers = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM, socket.IPPROTO_TCP)
    if not answers:
        raise OSError('no network addresses returned')
    validated = []
    for family, kind, proto, _, sockaddr in answers:
        if family not in (socket.AF_INET, socket.AF_INET6) or kind != socket.SOCK_STREAM:
            raise ValueError('blocked: unsupported network address')
        if not _public_address(sockaddr[0]) or sockaddr[1] != port:
            raise ValueError('blocked: non-public network destination')
        if family == socket.AF_INET6 and (sockaddr[2] or sockaddr[3]):
            raise ValueError('blocked: scoped network destination')
        validated.append((family, kind, proto, sockaddr))
    last_error = None
    for family, kind, proto, sockaddr in validated:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('network connection timed out')
        sock = socket.socket(family, kind, proto)
        try:
            sock.settimeout(remaining)
            # The sockaddr address is numeric. Do not use create_connection(host)
            # or any client which resolves the original hostname a second time.
            sock.connect(sockaddr)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('network connection timed out')
            sock.settimeout(remaining)
            return sock
        except OSError as exc:
            last_error = exc
            sock.close()
        except BaseException:
            sock.close()
            raise
    raise last_error or OSError('no usable network addresses')
