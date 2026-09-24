"""Session credentials or an explicitly unlocked, authenticated
encrypted vault.

Fernet and Scrypt use the maintained cryptography implementation:
https://cryptography.io/en/latest/fernet/
https://cryptography.io/en/latest/hazmat/primitives/key-derivation-functions/#scrypt
No passphrase, encryption key or plaintext credential is written by this module.
"""

import base64
import json
import os
import re
import stat
import tempfile
from pathlib import Path

from labcat.provider_catalog import API_KEY_PROVIDERS

SLOTS = ("materials_project", *API_KEY_PROVIDERS)


def valid_slot(slot: object) -> bool:
    return isinstance(slot, str) and (
        slot in SLOTS
        or re.fullmatch(r"(?:account|oauth)_[a-f0-9]{32}", slot) is not None
    )


class ConnectionError(RuntimeError):
    """Public-safe connection/storage error, without raw exception
    details."""


class ConnectionBusy(ConnectionError):
    """Another account operation is active; credentials remain
    unchanged."""


def read_private_file(path: Path, limit: int = 100_000) -> bytes:
    if path.is_symlink():
        raise ConnectionError("Connection storage cannot use symbolic links.")
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        )
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ConnectionError("Connection storage must be an ordinary file.")
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ConnectionError("Connection storage exceeded its size limit.")
        return data
    except OSError:
        raise ConnectionError("Connection storage could not be read.") from None


def unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def atomic_write(path: Path, value: dict):
    """One file replacement, restrictive POSIX modes; never retain
    secret backups."""
    if path.is_symlink() or path.parent.is_symlink():
        raise ConnectionError("Connection storage cannot use symbolic links.")
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(prefix=".labcat-", dir=path.parent)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, separators=(",", ":"), allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    except (OSError, ValueError):
        raise ConnectionError(
            "Connection settings could not be saved safely."
        ) from None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def validate_secrets(value: object) -> dict[str, str]:
    if (
        not isinstance(value, dict)
        or len(value) > 16
        or not all(map(valid_slot, value))
    ):
        raise ConnectionError("Unsupported credential fields.")
    if any(
        not isinstance(secret, str)
        or not re.fullmatch(
            (
                r"[A-Za-z0-9_=-]{8,32768}"
                if slot.startswith("oauth_")
                else r"[!-~]{8,4096}"
            ),
            secret,
        )
        for slot, secret in value.items()
    ):
        raise ConnectionError(
            "Credentials must be 8–4096 characters without whitespace."
        )
    return dict(value)


def _crypto():
    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    except ImportError:
        raise ConnectionError(
            "Encrypted credential support is not installed."
        ) from None
    return Fernet, Scrypt


class CredentialVault:
    """Caller serializes access.

    Memory lasts only for this application process.
    """

    def __init__(self, path: Path):
        self.path = path
        self.session: dict[str, str] = {}
        self._encrypted: dict[str, str] = {}
        self._document: dict | None = None
        self._fernet = None
        self._source = "unavailable"
        self._salt: str | None = None
        self.warnings: list[str] = []
        self._present = path.exists() or path.is_symlink()
        self._external_key()
        if self._present:
            try:
                document = json.loads(
                    read_private_file(path, 800_000),
                    object_pairs_hook=unique_json_object,
                )
                if (
                    not isinstance(document, dict)
                    or set(document) != {"version", "mode", "salt", "slots", "token"}
                    or type(document["version"]) is not int
                    or document["version"] != 1
                    or document["mode"] not in {"external", "passphrase"}
                    or not isinstance(document["token"], str)
                    or not isinstance(document["slots"], list)
                    or len(document["slots"]) > 16
                    or any(not valid_slot(slot) for slot in document["slots"])
                    or len(set(document["slots"])) != len(document["slots"])
                ):
                    raise ValueError
                self._document = document
                if document["mode"] == "passphrase":
                    salt = base64.urlsafe_b64decode(document["salt"])
                    if len(salt) != 16:
                        raise ValueError
                    self._salt = document["salt"]
                    self._source = "passphrase"
                    self._fernet = None
                elif self._fernet:
                    self._decrypt()
            except (ValueError, TypeError, RecursionError, ConnectionError):
                self._fernet = None
                self._encrypted = {}
                self._document = None
                self._salt = None
                self.warnings.append(
                    "Encrypted credentials are locked or unreadable. "
                    "Restore the vault key, unlock, or explicitly reset the vault."
                )

    def _external_key(self):
        try:
            direct = os.environ.get("LABCAT_VAULT_KEY")
            key_file = os.environ.get("LABCAT_VAULT_KEY_FILE")
            if direct and key_file:
                raise ConnectionError("Configure only one external vault key source.")
            if direct:
                key = direct.encode("ascii")
                source = "environment"
            elif key_file:
                key = read_private_file(Path(key_file), 256).strip()
                source = "file"
            else:
                return
            fernet, _ = _crypto()
            self._fernet = fernet(key)
            self._source = source
        except (ConnectionError, ValueError, UnicodeError):
            self._fernet = None
            self.warnings.append(
                "The external encryption key is unavailable or invalid."
            )

    def _decrypt(self):
        try:
            value = json.loads(
                self._fernet.decrypt(self._document["token"].encode("ascii"))
            )
            self._encrypted = validate_secrets(value)
            if set(self._encrypted) != set(self._document["slots"]):
                raise ValueError
        except Exception:
            self._encrypted = {}
            raise ConnectionError(
                "The encrypted vault could not be unlocked."
            ) from None

    def status(self) -> dict:
        return {
            "available": self._fernet is not None,
            "locked": self._present and self._fernet is None,
            "key_source": self._source,
            "exists": self._present,
            "can_create": not self._present and self._fernet is None,
        }

    def slots(self) -> dict[str, str]:
        saved = set(self._document["slots"]) if self._document else set()
        return {
            slot: (
                "session"
                if slot in self.session
                else (
                    "encrypted"
                    if slot in self._encrypted
                    else "locked" if slot in saved else "missing"
                )
            )
            for slot in set(SLOTS) | saved | set(self.session) | set(self._encrypted)
        }

    def get(self, slot: str) -> str | None:
        if not valid_slot(slot):
            raise ConnectionError("Unsupported credential slot.")
        return self.session.get(slot, self._encrypted.get(slot))

    def _persist(self, values: dict[str, str]):
        validate_secrets(values)
        if self._fernet is None:
            raise ConnectionError("Unlock or create the encrypted vault first.")
        token = self._fernet.encrypt(json.dumps(values).encode("utf-8")).decode("ascii")
        document = {
            "version": 1,
            "mode": "passphrase" if self._source == "passphrase" else "external",
            "salt": self._salt,
            "slots": sorted(values),
            "token": token,
        }
        atomic_write(self.path, document)
        self._document = document
        self._present = True
        self._encrypted = dict(values)

    def update(self, values: dict[str, str], forget: list[str], storage: str):
        validate_secrets(values)
        saved = set(self._document["slots"]) if self._document else set()
        if (
            any(not valid_slot(slot) for slot in forget)
            or len((saved | set(self.session) | set(values)) - set(forget)) > 16
        ):
            raise ConnectionError("Too many stored credentials or invalid removal.")
        if self._fernet is None and (
            storage == "encrypted" and values or saved & set(forget)
        ):
            raise ConnectionError(
                "Unlock the vault before changing encrypted credentials."
            )
        encrypted = {
            key: value for key, value in self._encrypted.items() if key not in forget
        }
        if storage == "encrypted":
            encrypted.update(values)
        if encrypted != self._encrypted or (storage == "encrypted" and values):
            self._persist(encrypted)
        for slot in forget:
            self.session.pop(slot, None)
        if storage == "session":
            self.session.update(values)
        else:
            for slot in values:
                self.session.pop(slot, None)

    def checkpoint(self):
        """Capture state in memory only while a connection update is
        committed."""
        return (
            dict(self.session),
            dict(self._encrypted),
            self._document,
            self._present,
        )

    def restore(self, checkpoint):
        """Restore prior ciphertext after a failed profile write."""
        session, encrypted, document, present = checkpoint
        if self._document != document:
            if document is not None:
                atomic_write(self.path, document)
            else:
                if self.path.is_symlink():
                    raise ConnectionError(
                        "Connection storage cannot use symbolic links."
                    )
                try:
                    self.path.unlink(missing_ok=True)
                except OSError:
                    raise ConnectionError(
                        "Credential rollback could not be saved."
                    ) from None
        self.session, self._encrypted = session, encrypted
        self._document, self._present = document, present

    def create(self, passphrase: str):
        if self._present or self._fernet is not None:
            raise ConnectionError(
                "A vault or external encryption key is already configured."
            )
        salt = os.urandom(16)
        self._derive(passphrase, salt)
        self._source = "passphrase"
        self._salt = base64.urlsafe_b64encode(salt).decode("ascii")
        try:
            self._persist({})
        except ConnectionError:
            self._fernet = None
            self._source = "unavailable"
            self._salt = None
            raise

    def _derive(self, passphrase: str, salt: bytes):
        if not isinstance(passphrase, str) or not 12 <= len(passphrase) <= 1024:
            raise ConnectionError(
                "Use a vault passphrase between 12 and 1024 characters."
            )
        fernet, scrypt = _crypto()
        try:
            encoded = passphrase.encode("utf-8")
        except UnicodeError:
            raise ConnectionError(
                "The vault passphrase has invalid characters."
            ) from None
        key = scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(encoded)
        self._fernet = fernet(base64.urlsafe_b64encode(key))

    def unlock(self, passphrase: str):
        if not self._document or self._document["mode"] != "passphrase":
            raise ConnectionError("This vault requires its configured external key.")
        try:
            self._derive(passphrase, base64.urlsafe_b64decode(self._salt))
            self._decrypt()
        except ConnectionError:
            self._fernet = None
            self._encrypted = {}
            raise

    def lock(self):
        if self._source != "passphrase":
            raise ConnectionError(
                "External-key vaults are controlled by the deployment."
            )
        self._fernet = None
        self._encrypted = {}
        self.session.clear()

    def reset(self):
        if self.path.is_symlink():
            raise ConnectionError("Connection storage cannot use symbolic links.")
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            raise ConnectionError("The encrypted vault could not be reset.") from None
        self.session.clear()
        self._fernet = None
        self._encrypted = {}
        self._document = None
        self._salt = None
        self._source = "unavailable"
        self._present = False
        self.warnings = []
        self._external_key()
