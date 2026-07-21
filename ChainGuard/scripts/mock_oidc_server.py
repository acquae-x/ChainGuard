"""最小 OIDC 身份提供方，仅供 ChainGuard 的 SSO 验收与测试使用。

实现真实流程里 ChainGuard 会打交道的两个端点：
  GET  /authorize  —— 校验 client_id/redirect_uri，带 code + state 跳回业务侧
  POST /token      —— 校验 client_id/client_secret/code，返回 HS256 签名的 id_token

签名密钥就是 client_secret，与 src/webapi/sso.py 的校验方式一致（沿用 rbac.py 的 HS256 取向）。
这是**测试替身**，不是生产 IdP：不做用户认证界面，登录主体由 --subject/--email 固定。
"""

from __future__ import annotations

import argparse
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib import parse

import jwt


class MockOidcProvider:
    def __init__(self, *, issuer: str, client_id: str, client_secret: str, subject: str, email: str, name: str) -> None:
        self.issuer = issuer
        self.client_id = client_id
        self.client_secret = client_secret
        self.subject = subject
        self.email = email
        self.name = name
        self._codes: dict[str, dict[str, Any]] = {}

    def issue_code(self, nonce: str, redirect_uri: str) -> str:
        code = secrets.token_urlsafe(16)
        self._codes[code] = {"nonce": nonce, "redirectUri": redirect_uri, "expiresAt": time.time() + 300}
        return code

    def redeem(self, code: str, client_id: str, client_secret: str) -> dict[str, Any] | None:
        entry = self._codes.pop(code, None)  # 授权码一次性
        if entry is None or entry["expiresAt"] < time.time():
            return None
        if client_id != self.client_id or client_secret != self.client_secret:
            return None
        now = int(time.time())
        claims = {
            "iss": self.issuer, "aud": self.client_id, "sub": self.subject,
            "email": self.email, "name": self.name, "nonce": entry["nonce"],
            "iat": now, "exp": now + 300,
        }
        return {"access_token": secrets.token_urlsafe(16), "token_type": "Bearer",
                "expires_in": 300, "id_token": jwt.encode(claims, self.client_secret, algorithm="HS256")}


def build_handler(provider: MockOidcProvider) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args: Any) -> None:  # 保持验收输出干净
            return

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            url = parse.urlparse(self.path)
            if url.path != "/authorize":
                self._json(404, {"error": "not_found"})
                return
            query = parse.parse_qs(url.query)
            client_id = (query.get("client_id") or [""])[0]
            redirect_uri = (query.get("redirect_uri") or [""])[0]
            state = (query.get("state") or [""])[0]
            nonce = (query.get("nonce") or [""])[0]
            if client_id != provider.client_id or not redirect_uri:
                self._json(400, {"error": "invalid_request"})
                return
            code = provider.issue_code(nonce, redirect_uri)
            separator = "&" if "?" in redirect_uri else "?"
            location = f"{redirect_uri}{separator}{parse.urlencode({'code': code, 'state': state})}"
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            url = parse.urlparse(self.path)
            if url.path != "/token":
                self._json(404, {"error": "not_found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            form = parse.parse_qs(self.rfile.read(length).decode("utf-8"))
            token = provider.redeem(
                (form.get("code") or [""])[0],
                (form.get("client_id") or [""])[0],
                (form.get("client_secret") or [""])[0],
            )
            if token is None:
                self._json(400, {"error": "invalid_grant"})
                return
            self._json(200, token)

    return Handler


def start_server(provider: MockOidcProvider, port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    """启动线程内 IdP，返回 (server, base_url)。port=0 时自动选空闲端口。"""
    server = ThreadingHTTPServer(("127.0.0.1", port), build_handler(provider))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def main() -> None:
    parser = argparse.ArgumentParser(description="ChainGuard SSO 验收用最小 OIDC 提供方")
    parser.add_argument("--port", type=int, default=8470)
    parser.add_argument("--client-id", default="chainguard-e2e")
    parser.add_argument("--client-secret", default="chainguard-e2e-secret-0123456789")
    parser.add_argument("--subject", default="sso-user-001")
    parser.add_argument("--email", default="sso.user@sso-demo.test")
    parser.add_argument("--name", default="SSO 演示用户")
    args = parser.parse_args()

    issuer = f"http://127.0.0.1:{args.port}"
    provider = MockOidcProvider(issuer=issuer, client_id=args.client_id, client_secret=args.client_secret,
                                subject=args.subject, email=args.email, name=args.name)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), build_handler(provider))
    print(f"mock OIDC provider listening on {issuer}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
