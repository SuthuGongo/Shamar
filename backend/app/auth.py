import base64
import hashlib
import hmac
import os
import secrets
import time

SECRET = (os.environ.get("SHAMAR_SECRET") or secrets.token_hex(32)).encode()
TOKEN_HOURS = 12
ITERATIONS = 200_000

DEMO_PASSWORD = os.environ.get("SHAMAR_DEMO_PASSWORD", "Shamar@2026")
DEMO_ACCOUNTS = {
    "thandi": "thandi.shamar@gmail.com",
    "sipho": "sipho.shamar@gmail.com",
}


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def check_password(password, stored):
    try:
        salt_b64, digest_b64 = stored.split("$")
    except (AttributeError, ValueError):
        return False
    expected = hash_password(password, base64.b64decode(salt_b64)).split("$")[1]
    return hmac.compare_digest(expected, digest_b64)


def _sign(payload):
    return hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()


def make_token(user_id):
    payload = f"{user_id}.{int(time.time()) + TOKEN_HOURS * 3600}"
    return f"{payload}.{_sign(payload)}"


def read_token(token):
    """Returns the user id, or None if the token is fake, edited or expired."""
    try:
        user_id, exp, sig = token.split(".")
    except (AttributeError, ValueError):
        return None
    if not hmac.compare_digest(sig, _sign(f"{user_id}.{exp}")):
        return None
    if int(exp) < time.time():
        return None
    return user_id
