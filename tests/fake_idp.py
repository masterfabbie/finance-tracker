"""A tiny OpenID Connect provider for tests: discovery, authorize, token, JWKS and userinfo.

`authorize` logs in whoever is set in `FakeIdP.next_user` without showing a page, then
redirects back with a code. ID tokens are real RS256 JWTs so authlib's validation runs.
"""

import secrets
import socket
import threading
import time
from urllib.parse import urlencode

import uvicorn
from joserfc import jwt
from joserfc.jwk import RSAKey
from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse


class FakeIdP:
    def __init__(self) -> None:
        self.key = RSAKey.generate_key(2048)
        self.key_id = "test-key"
        self.client_id = "proud-ledger"
        self.client_secret = "s3cret"
        self.next_user: dict = {"sub": "u-1", "preferred_username": "alice", "groups": []}
        self.codes: dict[str, dict] = {}
        self.port = _free_port()
        self.issuer = f"http://127.0.0.1:{self.port}/application/o/proud-ledger/"
        self.app = self._build()
        self._server: uvicorn.Server | None = None

    def _build(self) -> FastAPI:
        app = FastAPI()
        base = self.issuer.rstrip("/")

        @app.get("/application/o/proud-ledger/.well-known/openid-configuration")
        def discovery():
            return {
                "issuer": self.issuer,
                "authorization_endpoint": f"{base}/authorize",
                "token_endpoint": f"{base}/token",
                "userinfo_endpoint": f"{base}/userinfo",
                "jwks_uri": f"{base}/jwks",
                "response_types_supported": ["code"],
                "subject_types_supported": ["public"],
                "id_token_signing_alg_values_supported": ["RS256"],
                "code_challenge_methods_supported": ["S256"],
            }

        @app.get("/application/o/proud-ledger/jwks")
        def jwks():
            pub = self.key.as_dict(private=False)
            pub.update(kid=self.key_id, use="sig", alg="RS256")
            return {"keys": [pub]}

        @app.get("/application/o/proud-ledger/authorize")
        def authorize(request: Request):
            q = request.query_params
            assert q["client_id"] == self.client_id
            assert q.get("code_challenge_method") == "S256" and q.get("code_challenge")
            code = secrets.token_urlsafe(16)
            self.codes[code] = {"nonce": q.get("nonce"), "user": dict(self.next_user)}
            return RedirectResponse(q["redirect_uri"] + "?" + urlencode({"code": code, "state": q["state"]}), 302)

        @app.post("/application/o/proud-ledger/token")
        def token(code: str = Form(...), code_verifier: str = Form(None)):
            grant = self.codes.pop(code, None)
            if grant is None or not code_verifier:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            now = int(time.time())
            claims = {
                "iss": self.issuer, "aud": self.client_id, "iat": now, "exp": now + 300,
                "nonce": grant["nonce"], **grant["user"],
            }
            id_token = jwt.encode({"alg": "RS256", "kid": self.key_id}, claims, self.key)
            access = "at-" + secrets.token_urlsafe(8)
            self.codes[access] = grant  # remembered for /userinfo
            return {"access_token": access, "token_type": "Bearer", "expires_in": 300, "id_token": id_token}

        @app.get("/application/o/proud-ledger/userinfo")
        def userinfo(request: Request):
            grant = self.codes.get(request.headers.get("authorization", "").removeprefix("Bearer "))
            if grant is None:
                return JSONResponse({"error": "invalid_token"}, status_code=401)
            return grant["user"]

        return app

    def start(self) -> None:
        config = uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="warning")
        self._server = uvicorn.Server(config)
        threading.Thread(target=self._server.run, daemon=True).start()
        deadline = time.time() + 10
        while not self._server.started:
            if time.time() > deadline:
                raise RuntimeError("fake IdP did not start")
            time.sleep(0.05)

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
