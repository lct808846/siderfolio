"""Create a disposable preview identity from inside the loopback development stack."""

import os
import secrets
from urllib.parse import urlsplit
from uuid import uuid4

from astroagent.auth_config import AuthSettings
from astroagent.auth_security import email_address, hash_password
from astroagent.auth_store import AUTH_LOCK, AuthStore
from astroagent.config import LocalSettings


def main():
    auth = AuthSettings()
    local = LocalSettings()
    location = urlsplit(os.environ.get("ASTROAGENT_DATABASE_URL", ""))
    if (
        os.environ.get("ASTROAGENT_DEV_STACK") != "astroagent-dev"
        or not auth.local_http
        or auth.origin != "http://127.0.0.1:15273"
        or (location.hostname, location.path) != ("postgres", "/astroagent_dev")
    ):
        raise SystemExit("This operation requires the isolated Compose development stack.")

    identifier = uuid4()
    email, _ = email_address(f"preview-{identifier.hex[:10]}@example.org")
    password = "Aa9!" + secrets.token_urlsafe(24)
    with AuthStore(local, auth).connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(%s)", (AUTH_LOCK,))
        db.execute(
            "INSERT INTO public.auth_users"
            " (id,email_key,email_display,username,password_hash,active,namespace)"
            " VALUES (%s,%s,%s,'Preview',%s,true,%s)",
            (str(identifier), email, email, hash_password(password, auth), f"aa_{identifier.hex}"),
        )
    print(f"Local preview email: {email}\nLocal preview password: {password}")


if __name__ == "__main__":
    main()
