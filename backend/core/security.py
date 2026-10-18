from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from backend.core.config import is_known_compromised_secret, settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# settings always defines secret_key; a hardcoded fallback here would silently
# sign tokens with a key that is public in the repository.
SECRET_KEY = settings.secret_key
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 24 hours


def signing_key() -> str:
    """
    Resolve the JWT signing key, or refuse to produce one.

    Both failure modes matter: an unset key would make python-jose sign with an
    empty secret, and a key copied from an old branch is a key everyone with
    read access to the history already holds. Neither is allowed to issue a
    token, and neither error message echoes the value.
    """
    if not SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY is not configured. Set it in the environment "
            "(>=32 random characters); this service will not sign tokens with a "
            "built-in default."
        )
    if is_known_compromised_secret(SECRET_KEY):
        raise RuntimeError(
            "SECRET_KEY matches a credential previously published in this "
            "repository. Rotate it before issuing tokens."
        )
    return SECRET_KEY

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    import uuid
    jti = str(uuid.uuid4())
    to_encode.update({"exp": expire, "jti": jti})
    encoded_jwt = jwt.encode(to_encode, signing_key(), algorithm=ALGORITHM)
    return encoded_jwt
