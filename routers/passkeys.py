# routers/passkeys.py
"""WebAuthn / FIDO2 passkey endpoints.

Two flows live here:

  Registration (logged-in user adds a passkey to their account)
    POST /passkey/register/begin
       Server generates a registration challenge tied to this user, stashes
       it in their session, returns the options for navigator.credentials.create().
    POST /passkey/register/complete
       Browser POSTs back the AuthenticatorAttestationResponse. Server
       verifies the attestation, extracts the public key + credential ID,
       stores them.
    DELETE /passkey/{id}
       Removes a passkey from the user's account.
    PATCH /passkey/{id}
       Renames a passkey.

  Authentication (someone signs in with a passkey — no username/password)
    POST /passkey/login/begin
       Server generates an authentication challenge. Note: we don't ask for
       a username — we let the authenticator pick which credential to use
       (this is the "discoverable credentials" / passkey UX).
    POST /passkey/login/complete
       Browser POSTs back the signed assertion. Server looks up the
       credential, verifies the signature, logs the user in.

Notes on session usage:
  - The challenge MUST be the same one the server issued. We store it in
    `session["passkey_challenge"]` and clear it after use.
  - Login uses a separate session key from registration to prevent
    cross-flow confusion.

CSRF: these routes accept JSON, not form data, so a malicious cross-origin
form submission can't trigger them. Combined with same-site=lax cookies,
that's sufficient. (When we harden tomorrow, we'll add explicit CSRF tokens
to form-submitting endpoints.)
"""
import base64
import time
from datetime import datetime, timezone
from typing import Optional

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
from roles import STAFF_ROLES

router = APIRouter(tags=["Passkeys (WebAuthn)"])

# Maximum age of a stashed challenge before we consider it stale.
# WebAuthn doesn't actually care, but we expire to limit replay window.
CHALLENGE_TTL = 5 * 60

SESSION_LIFETIME_SHORT = 8 * 60 * 60
SESSION_LIFETIME_LONG = 30 * 24 * 60 * 60


# Encoding helpers. The webauthn library returns bytes; the browser sends
# base64url. We standardize on base64url-without-padding for storage so
# string comparisons work cleanly.
def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    # Add back padding the browser strips.
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + padding)


def _post_login_redirect(role: str) -> str:
    if role in STAFF_ROLES:
        return "/dashboard"
    return "/login?signed_in=1"


# =======================================================================
# Listing (for management UI)
# =======================================================================

@router.get("/passkey/list")
async def list_passkeys(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all passkeys registered by the current user."""
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


# =======================================================================
# Registration flow
# =======================================================================

@router.post("/passkey/register/begin")
async def register_begin(
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generates registration options and stashes the challenge in session.

    `exclude_credentials` lists credentials the user already has so the
    authenticator can refuse to re-enroll the same one twice (prevents the
    confusing "you already registered this device" situation)."""

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
        # User ID can be any byte string; we use the DB id encoded as bytes.
        user_id=str(current_user.id).encode("utf-8"),
        user_name=current_user.username,
        user_display_name=current_user.username,
        exclude_credentials=exclude,
        authenticator_selection=AuthenticatorSelectionCriteria(
            # "preferred" lets either platform (Touch ID) or roaming (USB key)
            # authenticators work. Most flexibility.
            user_verification=UserVerificationRequirement.PREFERRED,
            # "preferred" asks for a "discoverable" passkey — the kind that
            # works without typing a username. Standard modern passkey UX.
            resident_key=ResidentKeyRequirement.PREFERRED,
        ),
    )

    # Stash the challenge so /complete can verify the response refers to it.
    request.session["passkey_reg_challenge"] = _b64url_encode(options.challenge)
    request.session["passkey_reg_at"] = int(time.time())

    return JSONResponse(content=__import__("json").loads(options_to_json(options)))


@router.post("/passkey/register/complete")
async def register_complete(
    request: Request,
    payload: dict = Body(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Verifies the registration response and stores the passkey.

    The browser sends back a JSON object matching the WebAuthn
    PublicKeyCredential interface plus a `name` field we add for the
    user-friendly device label.
    """
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
        # Don't leak crypto error details to the client — just say it failed.
        raise HTTPException(status_code=400, detail=f"Passkey verification failed: {type(e).__name__}")

    # Persist. credential_id is bytes; we base64url-encode for storage so
    # we can use a plain String column and look it up easily during login.
    credential_id_b64 = _b64url_encode(verification.credential_id)

    # Defensive: make sure we don't double-insert the same credential ID
    # (would violate the unique constraint and produce a 500).
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

    # One-shot challenges: clear so the same registration can't be replayed.
    request.session.pop("passkey_reg_challenge", None)
    request.session.pop("passkey_reg_at", None)

    return {"id": pk.id, "name": pk.name, "created_at": pk.created_at.isoformat()}


@router.delete("/passkey/{passkey_id}")
async def delete_passkey(
    passkey_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a passkey from the user's account. Users can only delete
    their own passkeys."""
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
    """Rename a passkey — purely cosmetic, just for the user's own UI."""
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


# =======================================================================
# Authentication flow (passkey login)
# =======================================================================

@router.post("/passkey/login/begin")
async def login_begin(request: Request):
    """Generates auth options. We don't include `allow_credentials` because
    we want discoverable-credential UX: the user just clicks "Sign in",
    their device shows them which accounts have a passkey, they pick one.
    No username typing required."""

    options = generate_authentication_options(
        rp_id=RP_ID,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    request.session["passkey_login_challenge"] = _b64url_encode(options.challenge)
    request.session["passkey_login_at"] = int(time.time())

    return JSONResponse(content=__import__("json").loads(options_to_json(options)))


@router.post("/passkey/login/complete")
async def login_complete(
    request: Request,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    """Verify the assertion and complete login.

    Critical: passkeys are an *authentication* method that bypasses
    password entry. We must verify the cryptographic signature carefully
    and not return early on any partial match. The webauthn library
    handles signature verification; our job is to load the right
    credential by ID and pass it in.
    """
    challenge_b64 = request.session.get("passkey_login_challenge")
    challenge_at = request.session.get("passkey_login_at", 0)

    if not challenge_b64 or time.time() - challenge_at > CHALLENGE_TTL:
        raise HTTPException(status_code=400, detail="Login challenge expired. Please try again.")

    # Find the credential the browser claims to be using.
    credential_id = payload.get("id")
    if not credential_id:
        raise HTTPException(status_code=400, detail="Missing credential id")

    pk = db.query(models.Passkey).filter(
        models.Passkey.credential_id == credential_id
    ).first()
    if not pk:
        # Don't reveal whether the credential ID exists — just fail.
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

    # Update sign count to detect cloned credentials. If a future login comes
    # in with sign_count <= stored, the library will reject it.
    pk.sign_count = verification.new_sign_count
    pk.last_used_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()

    # Promote the session — passkey is "phishing-resistant single-factor",
    # so we skip the 2FA step even if the user has TOTP set up. (Passkey
    # IS the strong factor.)
    user = pk.user
    request.session.pop("passkey_login_challenge", None)
    request.session.pop("passkey_login_at", None)

    request.session["user_id"] = user.id
    request.session["username"] = user.username
    request.session["role"] = user.role
    request.session["expires_at"] = int(time.time()) + SESSION_LIFETIME_SHORT

    return {"redirect": _post_login_redirect(user.role)}
