"""Password hashing.

Argon2id rather than bcrypt: it is the current recommendation, it is memory-hard
against GPU attacks, and bcrypt silently truncates input beyond 72 bytes, which
turns a long passphrase into a shorter secret without telling anyone.
"""

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 12


def hash_password(password: str) -> str:
    """Return a self-describing hash: parameters and salt travel with it."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time verification that never raises on a wrong password."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the stored hash used weaker parameters than we use today."""
    return _hasher.check_needs_rehash(password_hash)
