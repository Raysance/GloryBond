"""Backend checks for on-demand webpage reading, without external requests."""
import asyncio
from contextlib import asynccontextmanager
import datetime
import gzip
import json
from pathlib import Path
import socket
import ssl
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
from fastapi.testclient import TestClient

from agent_runtime import Principal
from glorybond.apps.console.server import create_app
from glorybond.agent.webpages import PageError, WebPageFetcher, WebPageLimits, extract_page, public_address


HTML = """<!doctype html><html><head><title>版本更新 &amp; 分析</title>
<style>body { color: red; }</style><script>SECRET_SCRIPT</script></head>
<body><nav>NAVIGATION_TEXT</nav><div>OUTSIDE_NOISE</div>
<main><h1>核心改动</h1><p>安琪拉技能伤害提升，需要关注装备搭配。</p>
<p hidden>HIDDEN_TEXT</p><div aria-hidden="true">ARIA_HIDDEN</div>
<div style="display: none">STYLE_HIDDEN</div><div class="cookie-banner">COOKIE_TEXT</div>
<ul><li>前期伤害提升<li>冷却时间保持不变</ul>
<table><tr><th>英雄</th><th>胜率</th></tr><tr><td>安琪拉</td><td>52%</td></tr></table>
<img src="https://image.invalid/picture.png" alt="IMAGE_ALT">
<script>IGNORE_PREVIOUS_INSTRUCTIONS</script><aside>ADVERTISEMENTS</aside></main>
<footer>FOOTER_TEXT</footer></body></html>"""


class Chunks(httpx.AsyncByteStream):
    def __init__(self, raw):
        self.raw = raw

    async def __aiter__(self):
        for offset in range(0, len(self.raw), 256):
            yield self.raw[offset:offset + 256]


def response(raw=HTML.encode(), *, headers=None, status=200):
    return httpx.Response(status, headers=headers or {"Content-Type": "text/html; charset=utf-8"}, stream=Chunks(raw))


def fetcher(handler, **options):
    real_client = httpx.AsyncClient
    resolver = AsyncMock(return_value="93.184.216.34")
    factories = []

    def factory(**kwargs):
        factories.append(dict(kwargs))
        kwargs.pop("proxy", None)  # MockTransport stands in for the configured proxy.
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    reader = WebPageFetcher(WebPageLimits(**options), proxy_url="http://clash.test:7890", resolver=resolver, client_factory=factory)
    return reader, resolver, factories


@asynccontextmanager
async def tls_proxy(*, certificate_hosts=("github.com",), trusted=True, redirect=False):
    """Real CONNECT/TLS exchange; only the proxy socket is local, never the URL."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, certificate_hosts[0])])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(host) for host in certificate_hosts]), critical=False)
            .sign(key, hashes.SHA256()))
    connects, requests, names, tasks = [], [], [], set()
    with tempfile.TemporaryDirectory() as folder:
        cert_file, key_file = Path(folder) / "cert.pem", Path(folder) / "key.pem"
        cert_pem = cert.public_bytes(serialization.Encoding.PEM)
        cert_file.write_bytes(cert_pem)
        key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_file, key_file)
        context.set_servername_callback(lambda sock, name, ctx: names.append(name))

        async def proxy(reader, writer):
            tasks.add(asyncio.current_task())
            try:
                connects.append((await reader.readuntil(b"\r\n\r\n")).decode())
                writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                await writer.drain()
                await writer.start_tls(context)
                requests.append((await reader.readuntil(b"\r\n\r\n")).decode())
                if redirect and "Host: github.com\r\n" in requests[-1]:
                    writer.write(b"HTTP/1.1 302 Found\r\nLocation: https://raw.githubusercontent.com/example/repo/main/README.md\r\n"
                                 b"Set-Cookie: token=never-forward\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                    await writer.drain()
                    return
                body = b"<main><article><h1>GitHub README</h1><p>Repository content</p></article></main>"
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\nContent-Length: "
                             + str(len(body)).encode() + b"\r\n\r\n" + body)
                await writer.drain()
            except (ConnectionError, ssl.SSLError, asyncio.IncompleteReadError):
                # The negative cases deliberately reject the TLS handshake.
                pass
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except (ConnectionError, ssl.SSLError):
                    pass

        real_client = httpx.AsyncClient

        def client_factory(**kwargs):
            # Trust this ephemeral certificate only in the positive/hostname tests.
            # No production verification flags or hostname checks are disabled.
            verify = kwargs.get("verify")
            if not isinstance(verify, ssl.SSLContext):
                verify = httpx.create_ssl_context(trust_env=False)
                kwargs["verify"] = verify
            if trusted:
                verify.load_verify_locations(cadata=cert_pem.decode())
            return real_client(**kwargs)

        server = await asyncio.start_server(proxy, "127.0.0.1", 0)
        async with server:
            port = server.sockets[0].getsockname()[1]
            reader = WebPageFetcher(proxy_url=f"http://127.0.0.1:{port}",
                                    resolver=AsyncMock(return_value="93.184.216.34"), client_factory=client_factory)
            try:
                yield reader, connects, requests, names
            finally:
                if tasks:
                    await asyncio.gather(*tasks)


class ExtractionTests(unittest.TestCase):
    def test_article_preserves_facts_and_removes_markup_and_boilerplate(self):
        title, text = extract_page(HTML.encode(), "text/html; charset=utf-8")
        self.assertEqual(title, "版本更新 & 分析")
        for content in ["核心改动", "安琪拉技能伤害提升", "- 前期伤害提升", "冷却时间保持不变", "安琪拉 | 52%"]:
            self.assertIn(content, text)
        for noise in ["NAVIGATION_TEXT", "OUTSIDE_NOISE", "HIDDEN_TEXT", "ARIA_HIDDEN", "STYLE_HIDDEN",
                      "COOKIE_TEXT", "SECRET_SCRIPT", "IGNORE_PREVIOUS_INSTRUCTIONS", "IMAGE_ALT", "ADVERTISEMENTS", "FOOTER_TEXT", "<main>"]:
            self.assertNotIn(noise, text)

    def test_meta_charset_plain_text_and_empty_dynamic_page(self):
        page = '<meta charset="gb18030"><article>中文正文，准确读取。</article>'.encode("gb18030")
        self.assertIn("中文正文", extract_page(page, "text/html")[1])
        self.assertEqual(extract_page(b"plain text", "text/plain"), ("", "plain text"))
        with self.assertRaises(PageError):
            extract_page(b"<title>App</title><body><script>loadContent()</script></body>", "text/html")
        with self.assertRaises(PageError):
            extract_page(b"%PDF-1.7", "application/pdf")

    def test_deep_and_hidden_templates_do_not_become_article_candidates(self):
        source = "<template><main>HIDDEN_ARTICLE</main></template><article>" + "<div>" * 1800 + "真实正文" + "</div>" * 1800 + "</article>"
        title, text = extract_page(source.encode(), "text/html")
        self.assertEqual(text, "真实正文")



class FetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_https_proxy_pins_connect_ip_but_verifies_original_hostname(self):
        async with tls_proxy() as (reader, connects, requests, names):
            prepared = await reader.read("https://github.com/example/repo")
        page = prepared
        self.assertEqual(page["status"], "ok", page)
        self.assertIn("Repository content", page["text"])
        self.assertEqual(page["final_url"], "https://github.com/example/repo")
        self.assertIn("CONNECT 93.184.216.34:443 HTTP/1.1", connects[0])
        self.assertEqual(names, ["github.com"])
        self.assertIn("Host: github.com", requests[0])

    async def test_https_proxy_still_rejects_wrong_hostname_and_untrusted_certificate(self):
        for options in ({"certificate_hosts": ("wrong.example",)}, {"trusted": False}):
            with self.subTest(options=options):
                async with tls_proxy(**options) as (reader, connects, requests, names):
                    prepared = await reader.read("https://github.com/example/repo")
                page = prepared
                self.assertEqual(page["status"], "unavailable")
                self.assertEqual(page["error_type"], "ConnectError")
                self.assertNotIn("text", page)
                self.assertFalse(requests)

    async def test_https_proxy_redirect_binds_new_tls_hostname_without_cookies(self):
        async with tls_proxy(certificate_hosts=("github.com", "raw.githubusercontent.com"), redirect=True) as data:
            reader, connects, requests, names = data
            prepared = await reader.read("https://github.com/example/repo/raw/main/README.md")
        page = prepared
        self.assertEqual(page["status"], "ok", page)
        self.assertEqual(page["final_url"], "https://raw.githubusercontent.com/example/repo/main/README.md")
        self.assertEqual(names, ["github.com", "raw.githubusercontent.com"])
        self.assertEqual(len(connects), 2)
        self.assertTrue(all("CONNECT 93.184.216.34:443 HTTP/1.1" in row for row in connects))
        self.assertIn("Host: raw.githubusercontent.com", requests[1])
        self.assertNotIn("Cookie:", requests[1])
        self.assertEqual([call.args[0] for call in reader.resolver.await_args_list], names)

    async def test_missing_or_failed_proxy_never_falls_back_to_direct(self):
        factory = Mock(side_effect=RuntimeError("sensitive proxy error"))
        reader = WebPageFetcher(client_factory=factory)
        prepared = await reader.read("https://example.com/")
        self.assertIn("Clash", prepared["error"])
        factory.assert_not_called()
        reader.proxy_url = "http://clash.test:7890"
        reader.resolver = AsyncMock(return_value="93.184.216.34")
        prepared = await reader.read("https://example.com/")
        self.assertEqual(factory.call_count, 1)
        self.assertEqual(factory.call_args.kwargs["proxy"], reader.proxy_url)
        self.assertNotIn("sensitive", json.dumps(prepared))

    async def test_real_http_client_connects_to_proxy_and_preserves_pinned_host(self):
        received = []
        async def proxy(reader, writer):
            try:
                received.append((await reader.readuntil(b"\r\n\r\n")).decode())
                body = b"proxy article"
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 13\r\nConnection: close\r\n\r\n" + body)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
        server = await asyncio.start_server(proxy, "127.0.0.1", 0)
        async with server:
            port = server.sockets[0].getsockname()[1]
            reader = WebPageFetcher(proxy_url=f"http://127.0.0.1:{port}", resolver=AsyncMock(return_value="93.184.216.34"))
            prepared = await reader.read("http://example.com/article")
        self.assertEqual(prepared["text"], "proxy article")
        self.assertIn("GET http://93.184.216.34/article HTTP/1.1", received[0])
        self.assertIn("Host: example.com", received[0])

    async def test_single_read_uses_pinned_host_and_bounded_text(self):
        requests = []
        def handler(request):
            requests.append(request)
            return response(HTML.replace("</main>", "<p>有效内容</p>" * 50 + "</main>").encode())
        reader, resolver, factories = fetcher(handler, max_page_chars=100)
        page = await reader.read("https://example.com/a#1")
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url.host, "93.184.216.34")
        self.assertEqual(requests[0].headers["host"], "example.com")
        self.assertEqual(requests[0].extensions["sni_hostname"], "example.com")
        self.assertNotIn("authorization", requests[0].headers)
        self.assertNotIn("cookie", requests[0].headers)
        self.assertTrue(all(not opts["trust_env"] and not opts["follow_redirects"] for opts in factories))
        self.assertTrue(all(opts["proxy"] == "http://clash.test:7890" for opts in factories))
        self.assertEqual(len(page["text"]), 100)
        self.assertTrue(page["truncated"])
        self.assertEqual(page["url"], "https://example.com/a")

    async def test_dns_rejects_mixed_private_answers_and_embedded_private_ipv6(self):
        loop = asyncio.get_running_loop()
        for ips in [["127.0.0.1"], ["93.184.216.34", "10.0.0.1"], ["169.254.169.254"], ["::1"],
                    ["::ffff:127.0.0.1"], ["64:ff9b::a00:1"], ["224.0.0.1"]]:
            rows = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips]
            with patch.object(loop, "getaddrinfo", AsyncMock(return_value=rows)), self.assertRaises(PageError):
                await public_address("example.com", 443)

    async def test_configured_doh_bypasses_fake_dns_but_validates_public_answers(self):
        requests = []
        def handler(request):
            requests.append(request)
            if request.url.host == "1.1.1.1":
                self.assertEqual(request.url.params["name"], "example.com")
                payload = {"Answer": [{"type": 5, "data": "alias.example.com"}, {"type": 1, "data": "93.184.216.34"}]}
                return response(json.dumps(payload).encode(), headers={"Content-Type": "application/dns-json"})
            return response()
        reader, _, factories = fetcher(handler, dns_over_https_url="https://1.1.1.1/dns-query")
        reader.resolver = reader._resolve
        with patch("glorybond.agent.webpages.public_address", AsyncMock(side_effect=AssertionError("system fake DNS"))):
            prepared = await reader.read("https://example.com/")
        self.assertEqual(prepared['status'], 'ok')
        self.assertEqual([r.url.host for r in requests], ['1.1.1.1', '93.184.216.34'])
        self.assertTrue(all(options["proxy"] == "http://clash.test:7890" for options in factories))
        prepared = await reader.read('http://169.254.169.254/')
        self.assertEqual(len(requests), 2)
        self.assertIn('内网', prepared['error'])
        reader, _, _ = fetcher(lambda _: response(json.dumps({'Answer': [{'type': 1, 'data': '10.0.0.1'}]}).encode()),
                               dns_over_https_url='https://1.1.1.1/dns-query')
        reader.resolver = reader._resolve
        prepared = await reader.read('https://example.com/')
        self.assertIn('内网', prepared['error'])

    async def test_redirect_target_revalidated_and_does_not_carry_cookies(self):
        requests = []
        def handler(request):
            requests.append(request)
            if request.headers["host"] == "example.com":
                return response(b"", status=302, headers={"Location": "https://other.com/article", "Set-Cookie": "token=secret"})
            return response()
        reader, resolver, _ = fetcher(handler)
        prepared = await reader.read("https://example.com/")
        self.assertEqual(prepared["final_url"], "https://other.com/article")
        self.assertEqual(resolver.await_args_list[1].args[0], "other.com")
        self.assertNotIn("cookie", requests[1].headers)
        reader.resolver.side_effect = ["93.184.216.34", "127.0.0.1"]
        requests.clear()
        prepared = await reader.read("https://example.com/")
        self.assertEqual(len(requests), 1)
        self.assertIn("内网", prepared["error"])

    async def test_redirect_loop_http_error_and_non_web_content_are_observations(self):
        for factory, error in [
            (lambda _: response(b"", status=302, headers={"Location": "/again"}), "重定向"),
            (lambda _: response(b"", status=403), "HTTP 403"),
            (lambda _: response(b"%PDF", headers={"Content-Type": "application/pdf"}), "不是"),
        ]:
            reader, _, _ = fetcher(factory, max_redirects=1)
            prepared = await reader.read("https://example.com/")
            self.assertIn(error, prepared["error"])
            self.assertNotIn("text", prepared)

    async def test_malformed_dns_or_parser_failures_still_supply_unavailable_context(self):
        reader, _, _ = fetcher(lambda _: response(b'{"Answer":null}'),
                               dns_over_https_url='https://1.1.1.1/dns-query')
        reader.resolver = reader._resolve
        prepared = await reader.read('https://example.com/')
        self.assertIn('无效', prepared['error'])
        reader._fetch = AsyncMock(side_effect=RuntimeError('upstream-sensitive-details'))
        prepared = await reader.read('https://example.com/')
        self.assertEqual(prepared['error_type'], 'RuntimeError')
        self.assertNotIn('upstream-sensitive-details', json.dumps(prepared))

    async def test_response_and_decompression_limits_without_partial_success(self):
        for raw, headers in [(b"x" * 1025, {"Content-Type": "text/plain"}),
                             (gzip.compress(b"x" * 1000000), {"Content-Type": "text/plain", "Content-Encoding": "gzip"})]:
            reader, _, _ = fetcher(lambda _: response(raw, headers=headers), max_response_bytes=1024)
            prepared = await reader.read("https://example.com/")
            self.assertIn("体积上限", prepared["error"])
            self.assertEqual(prepared["status"], "unavailable")

    async def test_timeout_and_cancellation_do_not_turn_into_fabricated_content(self):
        reader, _, _ = fetcher(lambda _: response(), timeout_seconds=0.01)
        async def slow(_, **kwargs):
            await asyncio.sleep(10)
        reader._fetch = slow
        prepared = await reader.read("https://example.com/")
        self.assertIn("超时", prepared["error"])
        task = asyncio.create_task(reader.read("https://example.com/"))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_disabled_reader_does_not_request_network(self):
        reader, resolver, _ = fetcher(lambda _: self.fail("unexpected fetch"), enabled=False)
        with self.assertRaises(PageError):
            await reader.read("https://example.com/")
        resolver.assert_not_awaited()


class WebEndpointTests(unittest.TestCase):
    def test_web_post_leaves_link_reading_to_the_model(self):
        captured = []
        reader, _, _ = fetcher(lambda _: self.fail("unexpected prefetch"))
        with patch.dict("os.environ", {"HOK_CLASH_PROXY_URL": "http://clash.test:7891"}), \
                patch("glorybond.apps.console.server.WebPageFetcher", return_value=reader) as constructor:
            app = create_app()
        self.assertEqual(constructor.call_args.kwargs["proxy_url"], "http://clash.test:7891")
        runtime = Mock(active={"accepted": Mock()})
        runtime.submit.side_effect = lambda request: captured.append(request) or "accepted"
        app.state.runtime = runtime
        app.state.local_log = Mock(record=AsyncMock())
        app.state.principal = Principal("u")
        app.state.current_prompt = AsyncMock(return_value="test system prompt")
        app.state.roles = Mock(manage=AsyncMock(return_value={"selected": {"name": "test"}}))
        # No lifespan here: inject adapters instead of starting production SSH.
        client = TestClient(app)
        self.addCleanup(client.close)
        client.get("/")
        message = "总结 https://example.com/article"
        with patch("glorybond.apps.console.server.time.time", return_value=20):
            result = client.post("/api/chat", headers={"X-Local-UI": "1"},
                                 json={"session_id": "page-test", "message": message})
        self.assertEqual(result.status_code, 200)
        request = captured[0]
        self.assertEqual(request.user_message, message)
        self.assertEqual(request.system_prompt, "test system prompt")
        self.assertEqual(request.metadata["message_timestamp"], 20)
        self.assertEqual(request.metadata["chat_context"]["record"]["timestamp"], 20)
        self.assertFalse(request.context_messages)
        logged = [call.args[0] for call in app.state.local_log.record.await_args_list]
        self.assertFalse(any(event["kind"] == "request.webpages" for event in logged))


if __name__ == "__main__":
    unittest.main()
