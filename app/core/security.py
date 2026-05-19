"""Password hashing utilities using passlib/bcrypt."""

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ✍️ implement: return the bcrypt hash of `password`
def get_password_hash(password: str) -> str: ...


# ✍️ implement: return True if `plain_password` matches `hashed_password`
def verify_password(plain_password: str, hashed_password: str) -> bool: ...
