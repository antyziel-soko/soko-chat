"""Persistent login token storage through the operating system credential vault."""

import keyring

SERVICE_NAME = "Soko Chat"


def account_key(api_url: str, username: str) -> str:
    return f"{api_url.rstrip('/')}|{username.casefold()}"


def save_token(account_key: str, token: str) -> None:
    keyring.set_password(SERVICE_NAME, account_key, token)


def load_token(account_key: str) -> str | None:
    return keyring.get_password(SERVICE_NAME, account_key)


def delete_token(account_key: str) -> None:
    try:
        keyring.delete_password(SERVICE_NAME, account_key)
    except Exception:
        pass
