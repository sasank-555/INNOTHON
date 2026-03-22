from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.database import parse_object_id, users_collection
from app.security import decode_access_token


bearer_scheme = HTTPBearer(auto_error=False)


def authenticate_access_token(token: str) -> dict[str, str]:
    payload = decode_access_token(token)
    try:
        user = users_collection().find_one({"_id": parse_object_id(payload["sub"])})
    except Exception:
        user = None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists.",
        )
    return {"id": str(user["_id"]), "email": user["email"]}


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, str]:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    return authenticate_access_token(credentials.credentials)
