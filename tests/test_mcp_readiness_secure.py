"""Public readiness transport regression: all sockets and DNS are fake."""
import asyncio
import json
import socket
from unittest.mock import patch

import pytest
from delx_agent_utilities._internal import _public_socket
from delx_agent_utilities._internal._mcp_readiness import build_mcp_server_readiness_report
from tests.test_public_http_offline import FakeSocket, wire, answer


def response(payload):
    return wire(json.dumps(payload).encode())


@pytest.mark.asyncio
async def test_public_readiness_uses_pinned_post_and_get(monkeypatch):
    monkeypatch.setattr('os.environ', {})
    replies = [response({'result': {}}), response({'result': {'tools': [
        {'name': 'probe', 'description': 'A tool', 'inputSchema': {'type': 'object', 'properties': {}}}
    ]}}), response({'name': 'example'})]
    sockets = [FakeSocket(data) for data in replies]
    with patch.object(_public_socket.socket, 'getaddrinfo', side_effect=lambda host,port,*_: [answer('8.8.8.8',port)]), patch.object(_public_socket.socket, 'socket', side_effect=sockets):
        result = await build_mcp_server_readiness_report({'url': 'http://public.test', 'timeout': 3})
    assert result['ok'] is True
    assert result['checks']['mcp_initialize']['ok'] and result['checks']['tools_list']['tool_count'] == 1
    assert all(s.address == ('8.8.8.8',80) and s.closed for s in sockets)
    assert sockets[0].sent.startswith(b'POST /mcp HTTP/1.1') and b'"initialize"' in sockets[0].sent
    assert sockets[1].sent.startswith(b'POST /mcp HTTP/1.1') and b'"tools/list"' in sockets[1].sent
    assert sockets[2].sent.startswith(b'GET /.well-known/mcp.json HTTP/1.1')


@pytest.mark.asyncio
@pytest.mark.parametrize('ip', ['10.0.0.1', '169.254.169.254', '::1', 'fc00::1'])
async def test_private_dns_never_connects(ip, monkeypatch):
    monkeypatch.setattr('os.environ', {})
    with patch.object(_public_socket.socket, 'getaddrinfo', side_effect=lambda host,port,*_: [answer(ip,port)]), patch.object(_public_socket.socket, 'socket') as factory:
        result = await build_mcp_server_readiness_report({'url': 'http://public.test'})
    assert not result.get('ok')
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_credentials_redirect_and_oversized_fail_closed(monkeypatch):
    monkeypatch.setattr('os.environ', {})
    with patch.object(_public_socket.socket, 'getaddrinfo') as dns:
        result = await build_mcp_server_readiness_report({'url': 'http://user:secret@public.test'})
        assert not result.get('ok') and 'secret' not in str(result)
        dns.assert_not_called()
    for fake,expected in [(FakeSocket(wire(b'', '307 Temporary Redirect', b'Location: http://169.254.169.254/\r\n')), 'redirect'), (FakeSocket(wire(b'x' * 200001)), 'response')]:
        with patch.object(_public_socket.socket, 'getaddrinfo', side_effect=lambda host,port,*_: [answer('8.8.8.8',port)]), patch.object(_public_socket.socket, 'socket', return_value=fake) as factory:
            result = await build_mcp_server_readiness_report({'url': 'http://public.test'})
        assert not result.get('ok') and expected in str(result).lower()
        assert factory.call_count == 1 and fake.closed


@pytest.mark.asyncio
async def test_dns_rebinding_cannot_reach_second_socket(monkeypatch):
    monkeypatch.setattr('os.environ', {})
    fake = FakeSocket(response({'result': {}}))
    count = 0
    def dns(host, port, *_):
        nonlocal count
        count += 1
        return [answer('8.8.8.8' if count == 1 else '10.0.0.1', port)]
    with patch.object(_public_socket.socket, 'getaddrinfo', side_effect=dns), patch.object(_public_socket.socket, 'socket', return_value=fake) as factory:
        result = await build_mcp_server_readiness_report({'url': 'http://public.test'})
    assert not result.get('ok') and factory.call_count == 1 and count == 2


@pytest.mark.asyncio
async def test_injected_client_and_timeout_fail_closed(monkeypatch):
    monkeypatch.setattr('os.environ', {})
    assert (await build_mcp_server_readiness_report({'url': 'http://public.test'}, http_client=object()))['error'] == 'unsupported_client'
    with patch.object(_public_socket.socket, 'getaddrinfo', side_effect=TimeoutError):
        result = await build_mcp_server_readiness_report({'url': 'http://public.test'})
    assert result['error'] == 'timeout'


@pytest.mark.asyncio
async def test_proxy_and_tls_policy_applies_to_readiness(monkeypatch):
    from delx_agent_utilities._internal import _public_http
    from types import SimpleNamespace
    monkeypatch.setattr('os.environ', {'HTTPS_PROXY': 'http://user:secret@proxy.test:8080'})
    with patch.object(_public_socket.socket, 'getaddrinfo') as dns:
        result = await build_mcp_server_readiness_report({'url': 'https://public.test'})
    assert not result.get('ok') and 'secret' not in str(result)
    dns.assert_not_called()
    monkeypatch.setattr('os.environ', {})
    sockets = [FakeSocket(response({'result': {}})), FakeSocket(response({'result': {'tools': []}})), FakeSocket(response({}))]
    hostnames = []
    def wrap(sock, *, server_hostname):
        hostnames.append(server_hostname)
        return sock
    context = SimpleNamespace(wrap_socket=wrap)
    with patch.object(_public_socket.socket, 'getaddrinfo', side_effect=lambda host,port,*_: [answer('8.8.8.8',port)]), patch.object(_public_socket.socket, 'socket', side_effect=sockets), patch.object(_public_http.ssl, 'create_default_context', return_value=context):
        result = await build_mcp_server_readiness_report({'url': 'https://public.test'})
    assert result['ok'] and hostnames == ['public.test'] * 3
    assert context.minimum_version == _public_http.ssl.TLSVersion.TLSv1_2
