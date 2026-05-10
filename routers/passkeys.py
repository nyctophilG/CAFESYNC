# routers/passkeys.py
"""WebAuthn / FIDO2 passkey endpoints.

Two flows: registration (logged-in user adds a passkey) and authentication
(someone signs in with a passkey, no password).
"""
import base64
import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Depends, HTTPException, Body
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
    options_to_json,
)
from webauthn.helpers.structs import (
    PublicKeyCredentialDescriptor,
    UserVerificationRequirement,
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
)

import models
from database import get_db, RP_ID, RP_NAME, EXPECTED_ORIGINS
from auth_utils import get_current_user
from roles import post_login_path

router = APIRouter(tags=["Passkeys (WebAuthn)"])

CHALLENGE_TTL = 5 * 60
SESSION_LIFETIME_SHORT = 8 * 60 * 60


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + padding)


@router.get("/passkey/list")
async def list_passkeys(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.query(models.Passkey).filter(
        models.Passkey.user_id == current_user.id
    ).order_by(models.Passkey.created_at.desc()).all()
    return [
        {
            "id": pk.id,
            "name": pk.name,
            "created_at": pk.created_at.isoformat(),
            "last_used_at": pk.last_used_at.isoformat() if pk.last_used_at else None,
        }
        for pk in rows
    ]


@router.post("/passkey/register/begin")
async def register_begin(
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = db.query(models.Passkey).filter(
        models.Passkey.user_id == current_user.id
    ).all()
    exclude = [
        PublicKeyCredentialDescriptor(id=_b64url_decode(p.credential_id))
        for p in existing
    ]

    options = generate_registration_options(
        rp_id=RP_ID,
        rp_name=RP_NAME,
        user_id=str(current_user.id).encode("utf-8"),
        user_name=current_user.username,
        user_display_name=current_user.username,
        exclude_credentials=exclude,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.PREFERRED,
            resident_key=ResidentKeyRequirement.PREFERRED,
        ),
    )

    request.session["passkey_reg_challenge"] = _b64url_encode(options.challenge)
    request.session["passkey_reg_at"] = int(time.time())

    return JSONResponse(content=json.loads(options_to_json(options)))


@router.post("/passkey/register/complete")
async def register_complete(
    request: Request,
    payload: dict = Body(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    challenge_b64 = request.session.get("passkey_reg_challenge")
    challenge_at = request.session.get("passkey_reg_at", 0)

    if not challenge_b64 or time.time() - challenge_at > CHALLENGE_TTL:
        raise HTTPException(status_code=400, detail="Registration challenge expired. Please try again.")

    name = (payload.pop("name", None) or "").strip()[:64] or "Passkey"

    try:
        verification = verify_registration_response(
            credential=payload,
            expected_challenge=_b64url_decode(challenge_b64),
            expected_origin=EXPECTED_ORIGINS,
            expected_rp_id=RP_ID,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Passkey verification failed: {type(e).__name__}")

    credential_id_b64 = _b64url_encode(verification.credential_id)

    existing = db.query(models.Passkey).filter(
        models.Passkey.credential_id == credential_id_b64
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="This passkey is already registered.")

    pk = models.Passkey(
        user_id=current_user.id,
        credential_id=credential_id_b64,
        public_key=verification.credential_public_key,
        sign_count=verification.sign_count,
        name=name,
    )
    db.add(pk)
    db.commit()
    db.refresh(pk)

    request.session.pop("passkey_reg_challenge", None)
    request.session.pop("passkey_reg_at", None)

    return {"id": pk.id, "name": pk.name, "created_at": pk.created_at.isoformat()}


@router.delete("/passkey/{passkey_id}")
async def delete_passkey(
    passkey_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pk = db.query(models.Passkey).filter(
        models.Passkey.id == passkey_id,
        models.Passkey.user_id == current_user.id,
    ).first()
    if not pk:
        raise HTTPException(status_code=404, detail="Passkey not found")
    db.delete(pk)
    db.commit()
    return {"deleted": True}


@router.patch("/passkey/{passkey_id}")
async def rename_passkey(
    passkey_id: int,
    payload: dict = Body(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pk = db.query(models.Passkey).filter(
        models.Passkey.id == passkey_id,
        models.Passkey.user_id == current_user.id,
    ).first()
    if not pk:
        raise HTTPException(status_code=404, detail="Passkey not found")
    new_name = (payload.get("name") or "").strip()[:64]
    if not new_name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    pk.name = new_name
    db.commit()
    return {"id": pk.id, "name": pk.name}


@router.post("/passkey/login/begin")
async def login_begin(request: Request):
    options = generate_authentication_options(
        rp_id=RP_ID,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    request.session["passkey_login_challenge"] = _b64url_encode(options.challenge)
    request.session["passkey_login_at"] = int(time.time())

    return JSONResponse(content=json.loads(options_to_json(options)))


@router.post("/passkey/login/complete")
async def login_complete(
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    challenge_b64 = request.session.get("passkey_login_challenge")
    challenge_at = request.session.get("passkey_login_at", 0)

    if not challenge_b64 or time.time() - challenge_at > CHALLENGE_TTL:
        raise HTTPException(status_code=400, detail="Login challenge expired. Please try again.")

    credential_id = payload.get("id")
    if not credential_id:
        raise HTTPException(status_code=400, detail="Missing credential id")

    pk = db.query(models.Passkey).filter(
        models.Passkey.credential_id == credential_id
    ).first()
    if not pk:
        raise HTTPException(status_code=400, detail="Passkey verification failed")

    try:
        verification = verify_authentication_response(
            credential=payload,
            expected_challenge=_b64url_decode(challenge_b64),
            expected_origin=EXPECTED_ORIGINS,
            expected_rp_id=RP_ID,
            credential_public_key=pk.public_key,
            credential_current_sign_count=pk.sign_count,
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Passkey verification failed")

    pk.sign_count = verification.new_sign_count
    pk.last_used_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()

    user = pk.user
    request.session.pop("passkey_login_challenge", None)
    request.session.pop("passkey_login_at", None)

    request.session["user_id"] = user.id
    request.session["username"] = user.username
    request.session["role"] = user.role
    request.session["expires_at"] = int(time.time()) + SESSION_LIFETIME_SHORT

    return {"redirect": post_login_path(user.role)}
