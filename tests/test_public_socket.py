"""Offline regressions. All resolver/socket operations are fakes; no network."""
import ast
import importlib.util
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'src/delx_agent_utilities/_internal/_public_socket.py'
spec = importlib.util.spec_from_file_location('candidate_public_socket', MODULE)
public = importlib.util.module_from_spec(spec)
spec.loader.exec_module(public)


def answer(ip, port=443):
    family = socket.AF_INET6 if ':' in ip else socket.AF_INET
    sockaddr = (ip, port, 0, 0) if family == socket.AF_INET6 else (ip, port)
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', sockaddr)


class FakeSocket:
    def __init__(self, fail=False):
        self.closed = False
        self.connected = None
        self.fail = fail
    def settimeout(self, value):
        assert value > 0
    def connect(self, address):
        self.connected = address
        if self.fail:
            raise OSError('synthetic connection failure')
    def close(self):
        self.closed = True


class PublicSocketTests(unittest.TestCase):
    def test_nonpublic_and_mixed_answers_never_connect(self):
        for ip in ['127.0.0.1', '10.0.0.1', '169.254.169.254', '0.0.0.0', '100.64.0.1', '192.168.1.1', '224.0.0.1', '240.0.0.1', '::1', '::', 'fc00::1', 'fe80::1', 'ff02::1', '::ffff:127.0.0.1', '2002:7f00:1::', '2001::1', '64:ff9b::7f00:1', '64:ff9b:1::a00:1']:
            for answers in ([answer(ip)], [answer('8.8.8.8'), answer(ip)]):
                with self.subTest(ip=ip, mixed=len(answers)>1), patch.object(public.socket, 'getaddrinfo', return_value=answers), patch.object(public.socket, 'socket') as factory:
                    with self.assertRaises(ValueError):
                        public._connect_public('fake.example', 443, 1)
                    factory.assert_not_called()

    def test_pinned_numeric_connect_no_relookup(self):
        for ip in ['8.8.8.8', '2606:4700:4700::1111', '::ffff:8.8.8.8']:
            fake = FakeSocket()
            with self.subTest(ip=ip), patch.object(public.socket, 'getaddrinfo', side_effect=[[answer(ip)], AssertionError('relookup')]) as resolver, patch.object(public.socket, 'socket', return_value=fake), patch.object(public.socket, 'create_connection', side_effect=AssertionError('unsafe connection')):
                self.assertIs(public._connect_public('fake.example', 443, 1), fake)
                self.assertEqual(fake.connected, answer(ip)[4])
                self.assertEqual(resolver.call_count, 1)
                self.assertFalse(fake.closed)

    def test_retry_only_same_validated_set(self):
        failed, good = FakeSocket(True), FakeSocket()
        with patch.object(public.socket, 'getaddrinfo', return_value=[answer('8.8.8.8'), answer('1.1.1.1')]) as resolver, patch.object(public.socket, 'socket', side_effect=[failed, good]):
            self.assertIs(public._connect_public('fake.example', 443, 1), good)
            self.assertTrue(failed.closed)
            self.assertEqual(good.connected, ('1.1.1.1', 443))
            self.assertEqual(resolver.call_count, 1)

    def test_invalid_names_before_resolution(self):
        for host in ['', 'localhost', 'a.localhost', 'a.local', 'fe80::1%eth0', 'evil\nname', 'evil name']:
            with self.subTest(host=host), patch.object(public.socket, 'getaddrinfo') as resolver:
                with self.assertRaises(ValueError):
                    public._connect_public(host, 443, 1)
                resolver.assert_not_called()

    def test_resolver_fail_empty_and_expired_no_connect(self):
        for result in [[], OSError('synthetic DNS failure')]:
            with patch.object(public.socket, 'getaddrinfo', side_effect=result if isinstance(result, Exception) else None, return_value=result), patch.object(public.socket, 'socket') as factory:
                with self.assertRaises(OSError):
                    public._connect_public('fake.example', 443, 1)
                factory.assert_not_called()
        with patch.object(public.socket, 'getaddrinfo', return_value=[answer('8.8.8.8')]), patch.object(public.socket, 'socket') as factory, patch.object(public.time, 'monotonic', side_effect=[0, 2]):
            with self.assertRaises(TimeoutError):
                public._connect_public('fake.example', 443, 1)
            factory.assert_not_called()

    def test_integration_static_tls_sni_and_url_policy(self):
        # Parse, never import/execute the existing repository modules.
        helper = ast.parse((MODULE.parent / '_helpers.py').read_text())
        probe = next(n for n in helper.body if isinstance(n, ast.FunctionDef) and n.name == '_tls_probe_sync')
        calls = [n for n in ast.walk(probe) if isinstance(n, ast.Call)]
        self.assertTrue(any(isinstance(n.func, ast.Name) and n.func.id == '_connect_public' for n in calls))
        wraps = [n for n in calls if isinstance(n.func, ast.Attribute) and n.func.attr == 'wrap_socket']
        self.assertEqual(len(wraps), 1)
        self.assertTrue(any(k.arg == 'server_hostname' and isinstance(k.value, ast.Name) and k.value.id == 'host' for k in wraps[0].keywords))
        self.assertFalse(any(isinstance(n.func, ast.Attribute) and n.func.attr == 'create_connection' for n in calls))
        network = ast.parse((MODULE.parent / 'web/network.py').read_text())
        entry = next(n for n in network.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_tls_inspect')
        self.assertTrue(any(isinstance(n, ast.Name) and n.id == '_blocked_url_reason' for n in ast.walk(entry)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
