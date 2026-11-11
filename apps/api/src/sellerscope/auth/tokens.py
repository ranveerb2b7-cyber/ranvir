"""Verification of Supabase Auth (GoTrue) access tokens.

Supports asymmetric keys published via JWKS (RS256/ES256; current hosted Supabase default)
and the legacy shared HS256 secret (self-hosted GoTrue). Only explicitly allowed algorithms
are accepted; `alg: none` and algorithm confusion are rejected.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

import jwt
from jwt import PyJWKClient

from sellerscope.core.config import Settings
from sellerscope.core.errors import AppError

ASYMMETRIC_ALGORITHMS = frozenset({"RS256", "ES256"})
CLOCK_SKEW_SECONDS = 30


@dataclass(frozen=True, slots=True)
class TokenClaims:
    user_id: uuid.UUID
    email: str


def unauthorized(detail: str) -> AppError:
    return AppError(
        401, "unauthorized", "Unauthorized", detail, headers={"WWW-Authenticate": "Bearer"}
    )


class TokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self._issuer = settings.auth_jwt_issuer
        self._audience = settings.auth_jwt_audience
        self._secret = (
            settings.auth_jwt_secret.get_secret_value() if settings.auth_jwt_secret else None
        )
        self._jwks = (
            PyJWKClient(settings.auth_jwks_url, cache_keys=True, lifespan=600)
            if settings.auth_jwks_url
            else None
        )

    @property
    def configured(self) -> bool:
        return bool(self._issuer and (self._secret or self._jwks))

    async def verify(self, token: str) -> TokenClaims:
        if not self.configured:
            raise AppError(503, "auth_not_configured", "Authentication is not configured")
        try:
            alg = jwt.get_unverified_header(token).get("alg")
        except jwt.PyJWTError as exc:
            raise unauthorized("Malformed token") from exc

        key: object
        if alg == "HS256" and self._secret:
            key = self._secret
        elif alg in ASYMMETRIC_ALGORITHMS and self._jwks:
            try:
                key = (await asyncio.to_thread(self._jwks.get_signing_key_from_jwt, token)).key
            except jwt.PyJWKClientError as exc:
                raise unauthorized("Unknown signing key") from exc
        else:
            raise unauthorized("Unsupported token algorithm")

        try:
            claims = jwt.decode(
                token,
                key,  # type: ignore[arg-type]
                algorithms=[alg],
                audience=self._audience,
                issuer=self._issuer,
                leeway=CLOCK_SKEW_SECONDS,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise unauthorized("Token expired") from exc
        except jwt.PyJWTError as exc:
            raise unauthorized("Invalid token") from exc

        # Only real signed-in users: no anon/service_role keys, no anonymous sign-ins.
        if claims.get("role") != "authenticated" or claims.get("is_anonymous") is True:
            raise unauthorized("Token is not a user session")
        email = claims.get("email")
        if not isinstance(email, str) or "@" not in email:
            raise unauthorized("Token has no email")
        try:
            user_id = uuid.UUID(str(claims["sub"]))
        except ValueError as exc:
            raise unauthorized("Invalid subject") from exc
        return TokenClaims(user_id=user_id, email=email.lower())
