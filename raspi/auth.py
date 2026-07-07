#!/usr/bin/env python3
"""JWT + network-based + IP-allowlist authentication for the web API.

Local network requests (192.168.x.x, 10.x.x.x) auto-authenticate.
IPs verified via Discord bot are auto-authenticated for 30 days.
JWT tokens (login) are supported as a fallback.
All other external requests are blocked (403).
"""

import ipaddress
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext

from config import get
from database import is_ip_allowed

SECRET_KEY = get("auth", "jwt_secret", default="change-me")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

# ── Local network detection ─────────────────────────────────

LOCAL_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),  # loopback
    ipaddress.ip_network("10.0.0.0/8"),  # private
    ipaddress.ip_network("172.16.0.0/12"),  # private
    ipaddress.ip_network("192.168.0.0/16"),  # private
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("fc00::/7"),  # IPv6 private
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
]


def is_local_ip(ip_str: str) -> bool:
    """Check if an IP address is in a private/local range."""
    if not ip_str:
        return False
    try:
        addr = ipaddress.ip_address(ip_str)
        return any(addr in net for net in LOCAL_NETWORKS)
    except ValueError:
        return False


def normalize_ip(ip_str: str) -> str:
    """Canonicalize an IP address string (compressed form).

    IPv6 has multiple valid string representations (:: vs 0:0:0:0).
    This ensures we always store and compare the same form.
    """
    if not ip_str:
        return ""
    try:
        return ipaddress.ip_address(ip_str).compressed
    except ValueError:
        return ip_str.strip()


def is_cloudflare_request(request: Request) -> bool:
    """Check if request came through Cloudflare tunnel."""
    return bool(request.headers.get("cdn-loop", "").startswith("cloudflare"))


def get_client_ip(request: Request) -> str:
    """Get real client IP (normalized).

    For Cloudflare tunnel requests, uses CF-Connecting-IP to get the
    real client IP. IPv6 addresses are normalized to compressed form
    so comparisons with the allowlist always match.
    """
    raw = ""
    if is_cloudflare_request(request):
        cf_ip = request.headers.get("CF-Connecting-IP")
        if cf_ip:
            raw = cf_ip
        else:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                raw = forwarded.split(",")[0].strip()
            elif request.client:
                raw = request.client.host
            else:
                raw = "127.0.0.1"
    elif request.client:
        direct = request.client.host
        if is_local_ip(direct):
            raw = direct
        else:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                raw = forwarded.split(",")[0].strip()
            else:
                raw = direct
    else:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            raw = forwarded.split(",")[0].strip()
        elif request.client:
            raw = request.client.host
        else:
            raw = "unknown"
    return normalize_ip(raw)


# ── JWT helpers ─────────────────────────────────────────────


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def authenticate(username: str, password: str) -> str | None:
    """Validate credentials and return a JWT token, or None."""
    cfg_user = get("auth", "admin_username", default="admin")
    cfg_pw = get("auth", "admin_password", default="admin")
    if username == cfg_user and password == cfg_pw:
        return create_access_token({"sub": username})
    return None


# ── FastAPI dependencies ────────────────────────────────────


async def get_optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    """
    FastAPI dependency — auto-authenticates local network or allowlisted IPs.
    External IPs not in the allowlist are blocked (403).
    JWT tokens are supported as a fallback (cookie or Authorization header).
    """
    client_ip = get_client_ip(request)

    if is_local_ip(client_ip):
        return "local"

    if is_ip_allowed(client_ip):
        return "allowlisted"

    cookie_token = request.cookies.get("garden_token")
    if cookie_token:
        payload = decode_token(cookie_token)
        if payload is not None:
            return payload.get("sub", "unknown")

    if credentials is not None:
        payload = decode_token(credentials.credentials)
        if payload is not None:
            return payload.get("sub", "unknown")

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="IP not authorized — verify via /verify command on Discord "
        "or log in at /login",
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
):
    """Strict auth — always requires JWT token (used for login-sensitive operations)."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return payload.get("sub")
