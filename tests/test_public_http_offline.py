"""Offline real HTTP parser tests with fake DNS/sockets; no repository entrypoint."""
import ast
import asyncio
from contextlib import ExitStack
import importlib.util
import io
import ipaddress
import os
from pathlib import Path
import re
import socket
import sys
import time
import types
import unittest
from unittest.mock import patch
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parents[1] / 'src/delx_agent_utilities/_internal'
# Isolate only reviewed/new source files; never import package __init__/dispatcher.
pkg = types.ModuleType('offline_candidate')
pkg.__path__ = [str(ROOT)]
sys.modules[pkg.__name__] = pkg

def load(name):
    spec = importlib.util.spec_from_file_location('offline_candidate.'+name, ROOT/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

public = load('_public_socket')
http = load('_public_http')

# Execute only reviewed small helper definitions, with explicit stdlib globals.
from dataclasses import dataclass
from typing import Any
names = {'_CompatResponse','_decode_response_bytes','_HttpPolicyError',
         '_blocked_url_reason','_normalize_url','_redirect_destination',
         '_urllib_single_response','_urllib_request_response','_fetch_http_response'}
tree = ast.parse((ROOT/'_helpers.py').read_text())
selected = ast.Module(body=[n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names], type_ignores=[])
helpers = dict(dataclass=dataclass, Any=Any, re=re, socket=socket, ipaddress=ipaddress,
               urljoin=urljoin,urlparse=urlparse,time=time,asyncio=asyncio,
               _request_public_http=http._request_public_http)
exec(compile(selected,'reviewed_helper_definitions','exec'),helpers)

class FakeSocket:
    def __init__(self, wire):
        self.wire = wire
        self.sent = b''
        self.address = None
        self.closed = False
    def settimeout(self, value):
        assert value > 0
    def connect(self, address):
        self.address = address
    def sendall(self, data):
        self.sent += data
    def makefile(self, mode):
        assert mode == 'rb'
        return io.BytesIO(self.wire)
    def close(self):
        self.closed = True

def answer(ip, port):
    v6 = ':' in ip
    return (socket.AF_INET6 if v6 else socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'', (ip,port,0,0) if v6 else (ip,port))

def wire(body=b'ok', status='200 OK', headers=b''):
    return b'HTTP/1.1 '+status.encode()+b'\r\nContent-Length: '+str(len(body)).encode()+b'\r\n'+headers+b'\r\n'+body

class OfflineHTTPTests(unittest.TestCase):
    def setUp(self):
        # Create asyncio's own local wakeup socketpair before mocking outbound
        # sockets. It never connects to any network address.
        self.loop = asyncio.new_event_loop()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # Test-only process mapping; never change operator/system configuration.
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
    def tearDown(self):
        self.loop.run_until_complete(self.loop.shutdown_default_executor())
        self.loop.close()
    def fixture(self, responses, resolve):
        sockets = [FakeSocket(r) for r in responses]
        self.stack.enter_context(patch.object(public.socket,'getaddrinfo',side_effect=resolve))
        factory = self.stack.enter_context(patch.object(public.socket,'socket',side_effect=sockets))
        self.stack.enter_context(patch.object(public.socket,'create_connection',side_effect=AssertionError('unvalidated DNS lookup')))
        return sockets, factory

    def test_hostname_host_header_path_and_no_proxy(self):
        sockets,_ = self.fixture([wire(b'hello')], lambda host,port,*args: [answer('8.8.8.8',port)])
        with patch.dict(os.environ,{'HTTP_PROXY':'','http_proxy':' ', 'ALL_PROXY':'', 'NO_PROXY':'*'}):
            status,body,headers,reason=http._request_public_http('http://example.test:8080/é?q=✓',timeout=1,method='GET')
        self.assertEqual((status,body,reason),(200,b'hello','OK'))
        self.assertEqual(sockets[0].address,('8.8.8.8',8080))
        self.assertIn(b'Host: example.test:8080\r\n',sockets[0].sent)
        self.assertIn(b'GET /%C3%A9?q=%E2%9C%93 HTTP/1.1',sockets[0].sent)
        self.assertIn(b'Accept-Encoding: identity',sockets[0].sent)
        self.assertTrue(sockets[0].closed)

    def test_proxy_configuration_fails_closed_without_disclosing_credentials(self):
        for scheme, keys in [('http', ['HTTP_PROXY','http_proxy','ALL_PROXY','all_proxy']),
                             ('https',['HTTPS_PROXY','https_proxy','ALL_PROXY','all_proxy'])]:
            for key in keys:
                with self.subTest(scheme=scheme,key=key), patch.dict(os.environ,{key:'http://user:secret@proxy.test:8080','NO_PROXY':'*','no_proxy':'public.test'}), patch.object(public.socket,'getaddrinfo') as dns, patch.object(public.socket,'socket') as factory:
                    with self.assertRaisesRegex(ValueError,'configured proxy') as caught:
                        http._request_public_http(scheme+'://public.test/',timeout=1,method='GET')
                    self.assertNotIn('secret',str(caught.exception))
                    self.assertNotIn('proxy.test',str(caught.exception))
                    dns.assert_not_called();factory.assert_not_called()

    def test_tls_original_sni_and_verification_failure_no_fallback(self):
        sockets,factory = self.fixture([wire(),wire()],lambda host,port,*args:[answer('8.8.8.8',port)])
        context = types.SimpleNamespace(wrap_socket=lambda sock,server_hostname: (self.assertEqual(server_hostname,'example.test') or sock))
        with patch.object(http.ssl,'create_default_context',return_value=context) as default:
            self.assertEqual(http._request_public_http('https://example.test/',timeout=1,method='GET')[0],200)
            default.assert_called_once_with()
            self.assertEqual(context.minimum_version, http.ssl.TLSVersion.TLSv1_2)
        context.wrap_socket=lambda *args,**kw: (_ for _ in ()).throw(http.ssl.SSLCertVerificationError('fake mismatch'))
        with patch.object(http.ssl,'create_default_context',return_value=context):
            with self.assertRaises(http.ssl.SSLCertVerificationError):
                http._request_public_http('https://example.test/',timeout=1,method='GET')
        self.assertEqual(factory.call_count,2)
        self.assertTrue(all(s.closed for s in sockets))

    def test_real_context_retains_certificate_and_hostname_validation(self):
        # Construct stdlib context locally; no handshake or network access.
        context = http.ssl.create_default_context()
        context.minimum_version = http.ssl.TLSVersion.TLSv1_2
        self.assertEqual(context.minimum_version, http.ssl.TLSVersion.TLSv1_2)
        self.assertEqual(context.verify_mode, http.ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_redirect_rebind_rejected_before_second_socket(self):
        calls=[]
        def dns(host,port,*args):
            calls.append(host)
            return [answer('8.8.8.8' if len(calls)==1 else '127.0.0.1',port)]
        sockets,factory=self.fixture([wire(b'', '302 Found', b'Location: /next\r\n')],dns)
        result,error=self.loop.run_until_complete(helpers['_fetch_http_response']('http://example.test/'))
        self.assertIsNone(result)
        self.assertIn('non-public',error)
        self.assertEqual(calls,['example.test','example.test'])
        self.assertEqual(factory.call_count,1)
        self.assertTrue(sockets[0].closed)

    def test_redirect_cross_host_relative_then_head(self):
        hosts=[]
        def dns(host,port,*args):
            hosts.append(host);return [answer('8.8.8.8',port)]
        sockets,_=self.fixture([wire(b'', '302 Found',b'Location: http://second.test/a\r\n'),wire(b'', '307 Temporary Redirect',b'Location: ../b\r\n'),wire(b'ignored')],dns)
        result=helpers['_urllib_request_response']('http://first.test/',method='HEAD')
        self.assertEqual(result.url,'http://second.test/b')
        self.assertEqual(result.text,'')
        self.assertEqual(hosts,['first.test','second.test','second.test'])
        self.assertIn(b'Host: second.test\r\n',sockets[2].sent)
        self.assertTrue(all(s.sent.startswith(b'HEAD ') and s.closed for s in sockets))

    def test_redirect_limit_scheme_and_credentials(self):
        for location in ['file:///etc/passwd','http://127.0.0.1/','http://user:password@public.test/']:
            with self.subTest(location=location):
                fake=FakeSocket(wire(b'', '302 Found',f'Location: {location}\r\n'.encode()))
                with patch.object(public.socket,'getaddrinfo',return_value=[answer('8.8.8.8',80)]),patch.object(public.socket,'socket',return_value=fake) as factory:
                    response,error=self.loop.run_until_complete(helpers['_fetch_http_response']('http://public.test/'))
                    self.assertIsNone(response);self.assertTrue(error);self.assertEqual(factory.call_count,1)
        sockets,factory=self.fixture([wire(b'', '302 Found',b'Location: /again\r\n') for _ in range(6)],lambda host,port,*args:[answer('8.8.8.8',port)])
        result,error=self.loop.run_until_complete(helpers['_fetch_http_response']('http://public.test/'))
        self.assertIsNone(result);self.assertIn('too many',error);self.assertEqual(factory.call_count,6)

    def test_bytes_encoding_errors_close(self):
        for data,cap,error in [(wire(b'12345'),4,'exceeds'),(wire(b'compressed',headers=b'Content-Encoding: gzip\r\n'),100,'encoding')]:
            fake=FakeSocket(data)
            with patch.object(public.socket,'getaddrinfo',return_value=[answer('8.8.8.8',80)]),patch.object(public.socket,'socket',return_value=fake):
                with self.assertRaisesRegex(ValueError,error):
                    http._request_public_http('http://public.test/',timeout=1,method='GET',max_bytes=cap)
                self.assertTrue(fake.closed)

    def test_error_status_charset_ipv6_authority(self):
        sockets,_=self.fixture([wire(b'caf\xe9','404 Not Found',b'Content-Type: text/plain; charset=iso-8859-1\r\n')],lambda host,port,*args:[answer('2606:4700:4700::1111',port)])
        result=helpers['_urllib_single_response']('http://[2606:4700:4700::1111]:8080/')
        self.assertEqual((result.status_code,result.text),(404,'café'))
        self.assertIn(b'Host: [2606:4700:4700::1111]:8080\r\n',sockets[0].sent)

    def test_mixed_dns_never_connects(self):
        _,factory=self.fixture([],lambda host,port,*args:[answer('8.8.8.8',port),answer('10.0.0.1',port)])
        with self.assertRaisesRegex(ValueError,'non-public'):
            http._request_public_http('http://public.test/',timeout=1,method='GET')
        factory.assert_not_called()

if __name__=='__main__':
    unittest.main(verbosity=2)
