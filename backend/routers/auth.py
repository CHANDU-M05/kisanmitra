from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from backend.core.database import get_db
from backend.core.models import AdminUser, RevokedToken
from backend.core.security import verify_password, create_access_token, signing_key, ALGORITHM
from typing import Annotated
from jose import JWTError, jwt
import datetime

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# In-memory rate limiting state for login brute-force protection
_FAILED_LOGIN_ATTEMPTS: dict[str, tuple[int, datetime.datetime | None]] = {}
MAX_LOGIN_ATTEMPTS = 3
LOCKOUT_DURATION_MINUTES = 15

@router.post("/login")
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: AsyncSession = Depends(get_db)
):
    username = form_data.username.strip().lower() if form_data.username else ""
    now = datetime.datetime.utcnow()
    
    # Check if account is locked out
    if username in _FAILED_LOGIN_ATTEMPTS:
        count, lock_until = _FAILED_LOGIN_ATTEMPTS[username]
        if lock_until and now < lock_until:
            remaining_mins = max(1, int((lock_until - now).total_seconds() // 60))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Account locked out due to repeated failed logins. Please try again in {remaining_mins} minute(s).",
            )
        elif lock_until and now >= lock_until:
            # Lockout expired, reset counter
            _FAILED_LOGIN_ATTEMPTS.pop(username, None)
            count = 0

    result = await db.execute(select(AdminUser).where(AdminUser.username == form_data.username))
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        current_count = _FAILED_LOGIN_ATTEMPTS.get(username, (0, None))[0] + 1
        if current_count >= MAX_LOGIN_ATTEMPTS:
            lock_until = now + datetime.timedelta(minutes=LOCKOUT_DURATION_MINUTES)
            _FAILED_LOGIN_ATTEMPTS[username] = (current_count, lock_until)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many failed login attempts (3/3). Account locked for {LOCKOUT_DURATION_MINUTES} minutes.",
            )
        else:
            _FAILED_LOGIN_ATTEMPTS[username] = (current_count, None)
            attempts_left = MAX_LOGIN_ATTEMPTS - current_count
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Incorrect username or password. {attempts_left} attempt(s) remaining.",
                headers={"WWW-Authenticate": "Bearer"},
            )
    
    # Success: clear failed attempts tracker
    _FAILED_LOGIN_ATTEMPTS.pop(username, None)
    
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, signing_key(), algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        jti: str = payload.get("jti")
        exp: int = payload.get("exp")
        if username is None or jti is None or exp is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    # Check if token is revoked
    result = await db.execute(select(RevokedToken).where(RevokedToken.jti == jti))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    user_result = await db.execute(select(AdminUser).where(AdminUser.username == username))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    
    # Attach JWT details to user object to maintain backward compatibility
    user.jti = jti
    user.exp = exp
    return user

async def prune_expired_tokens(db: AsyncSession):
    try:
        await db.execute(delete(RevokedToken).where(RevokedToken.expires_at < datetime.datetime.utcnow()))
        await db.commit()
    except Exception as e:
        import logging
        logging.error(f"Failed to prune tokens: {e}")

@router.post("/logout")
async def logout(
    background_tasks: BackgroundTasks,
    current_user: AdminUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    jti = current_user.jti
    exp_timestamp = current_user.exp
    expires_at = datetime.datetime.utcfromtimestamp(exp_timestamp)
    
    revoked_token = RevokedToken(jti=jti, expires_at=expires_at)
    db.add(revoked_token)
    await db.commit()
    
    # Prune expired tokens seamlessly in the background
    background_tasks.add_task(prune_expired_tokens, db)
    
    return {"message": "Successfully logged out. Token revoked."}
