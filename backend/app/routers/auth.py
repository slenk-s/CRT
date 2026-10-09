"""认证路由：登录 / 当前用户 / 改密。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..schemas import ChangePasswordRequest, LoginRequest, TokenResponse, UserOut
from ..security import create_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.get(User, body.emp_id.strip())
    if not user or not user.active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "工号或口令错误")
    token = create_token(user.emp_id, user.name, user.role)
    return TokenResponse(token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "原口令不正确")
    if body.new_password == body.old_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "新口令不能与原口令相同")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = 0
    db.add(user)
    db.commit()
    return {"ok": True, "message": "口令已更新"}