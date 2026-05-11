# tests/unit/test_auth_utils.py
"""Unit tests for auth_utils.py — covers bcrypt, TOTP, backup codes, and
the FastAPI dependencies (get_current_user / require_admin / etc).
"""
import pytest


# ---------- Password hashing ----------

class TestPasswordHashing:

    def test_hash_roundtrip(self, app_module):
        from auth_utils import hash_password, verify_password
        h = hash_password("hunter2")
        assert verify_password("hunter2", h)

    def test_wrong_password_rejected(self, app_module):
        from auth_utils import hash_password, verify_password
        h = hash_password("hunter2")
        assert not verify_password("wrong", h)

    def test_hashes_are_random_per_call(self, app_module):
        """bcrypt salts each hash, so the same password never hashes the same way."""
        from auth_utils import hash_password
        a, b = hash_password("same"), hash_password("same")
        assert a != b

    def test_password_too_long_raises(self, app_module):
        from auth_utils import hash_password, BCRYPT_MAX_BYTES
        too_long = "x" * (BCRYPT_MAX_BYTES + 1)
        with pytest.raises(ValueError, match="bytes"):
            hash_password(too_long)

    def test_unicode_password_byte_length_check(self, app_module):
        """Multi-byte UTF-8 characters can exceed the 72-byte limit at fewer chars."""
        from auth_utils import hash_password, BCRYPT_MAX_BYTES
        # "🔑" = 4 UTF-8 bytes. 19 of them = 76 bytes > 72.
        too_long = "🔑" * 19
        with pytest.raises(ValueError):
            hash_password(too_long)

    def test_verify_password_too_long_returns_false(self, app_module):
        from auth_utils import hash_password, verify_password, BCRYPT_MAX_BYTES
        h = hash_password("real_password")
        # Verifying with an over-length string should return False, not raise.
        assert not verify_password("x" * (BCRYPT_MAX_BYTES + 1), h)

    def test_verify_password_against_garbage_hash_returns_false(self, app_module):
        from auth_utils import verify_password
        assert not verify_password("anything", "not-a-real-bcrypt-hash")

    def test_authenticate_user_success(self, app_module, db, make_user):
        from auth_utils import authenticate_user
        u = make_user("alice")
        result = authenticate_user(db, "alice", u._test_password)
        assert result is not None
        assert result.id == u.id

    def test_authenticate_user_wrong_password(self, app_module, db, make_user):
        from auth_utils import authenticate_user
        make_user("alice")
        assert authenticate_user(db, "alice", "wrong_password") is None

    def test_authenticate_user_unknown_username(self, app_module, db):
        """Unknown usernames go through the dummy-hash path to prevent enumeration."""
        from auth_utils import authenticate_user
        assert authenticate_user(db, "nobody", "any_password") is None


# ---------- TOTP ----------

class TestTOTP:

    def test_generate_totp_secret_is_base32(self, app_module):
        from auth_utils import generate_totp_secret
        secret = generate_totp_secret()
        assert len(secret) >= 16
        # base32 alphabet
        assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for c in secret)

    def test_two_secrets_differ(self, app_module):
        from auth_utils import generate_totp_secret
        assert generate_totp_secret() != generate_totp_secret()

    def test_provisioning_uri_includes_issuer(self, app_module):
        from auth_utils import generate_totp_secret, totp_provisioning_uri
        s = generate_totp_secret()
        uri = totp_provisioning_uri(s, "alice")
        assert uri.startswith("otpauth://totp/")
        assert "CafeSync" in uri
        assert "alice" in uri
        assert s in uri

    def test_qr_data_uri_is_png(self, app_module):
        from auth_utils import generate_totp_secret, totp_qr_data_uri
        uri = totp_qr_data_uri(generate_totp_secret(), "alice")
        assert uri.startswith("data:image/png;base64,")
        # Base64 of a real PNG starts with "iVBORw0KGgo" (PNG magic + base64).
        assert "iVBORw0KGgo" in uri

    def test_verify_totp_accepts_current_code(self, app_module):
        import pyotp
        from auth_utils import generate_totp_secret, verify_totp
        s = generate_totp_secret()
        code = pyotp.TOTP(s).now()
        assert verify_totp(s, code)

    def test_verify_totp_rejects_wrong_code(self, app_module):
        from auth_utils import generate_totp_secret, verify_totp
        assert not verify_totp(generate_totp_secret(), "000000")

    def test_verify_totp_handles_empty_inputs(self, app_module):
        from auth_utils import verify_totp
        assert not verify_totp("", "123456")
        assert not verify_totp("ABCDEFGHIJKLMNOP", "")
        assert not verify_totp(None, "123456")

    def test_verify_totp_handles_garbage(self, app_module):
        """Bad input should return False, never raise."""
        from auth_utils import verify_totp
        assert not verify_totp("not-base32", "123456")


# ---------- Backup codes ----------

class TestBackupCodes:

    def test_generate_returns_correct_count(self, app_module):
        from auth_utils import generate_backup_codes, BACKUP_CODE_COUNT
        codes = generate_backup_codes()
        assert len(codes) == BACKUP_CODE_COUNT

    def test_codes_are_unique(self, app_module):
        from auth_utils import generate_backup_codes
        codes = generate_backup_codes()
        assert len(set(codes)) == len(codes)

    def test_codes_are_formatted_with_dash(self, app_module):
        from auth_utils import generate_backup_codes, BACKUP_CODE_LENGTH
        for code in generate_backup_codes():
            assert "-" in code
            cleaned = code.replace("-", "")
            assert len(cleaned) == BACKUP_CODE_LENGTH

    def test_hash_and_verify_roundtrip(self, app_module):
        from auth_utils import hash_backup_code, verify_backup_code_against_hash
        code = "ABCDE-FGHIJ"
        h = hash_backup_code(code)
        assert verify_backup_code_against_hash(code, h)

    def test_verify_normalizes_dashes_and_case(self, app_module):
        """User input variations shouldn't break verification."""
        from auth_utils import hash_backup_code, verify_backup_code_against_hash
        h = hash_backup_code("ABCDE-FGHIJ")
        assert verify_backup_code_against_hash("abcde-fghij", h)  # lowercase
        assert verify_backup_code_against_hash("ABCDEFGHIJ", h)   # no dash
        assert verify_backup_code_against_hash("abcdefghij", h)   # both

    def test_verify_rejects_wrong_code(self, app_module):
        from auth_utils import hash_backup_code, verify_backup_code_against_hash
        h = hash_backup_code("ABCDE-FGHIJ")
        assert not verify_backup_code_against_hash("WRONG-WRONG", h)

    def test_verify_rejects_empty(self, app_module):
        from auth_utils import verify_backup_code_against_hash
        assert not verify_backup_code_against_hash("", "x")
        assert not verify_backup_code_against_hash("x", "")

    def test_verify_handles_malformed_hash(self, app_module):
        from auth_utils import verify_backup_code_against_hash
        assert not verify_backup_code_against_hash("ABCDE-FGHIJ", "not-a-hash")

    def test_consume_backup_code_marks_used(self, app_module, db, make_user):
        import models
        from auth_utils import hash_backup_code, consume_backup_code

        user = make_user("alice")
        db.add(models.BackupCode(user_id=user.id, code_hash=hash_backup_code("ABCDE-FGHIJ")))
        db.commit()

        assert consume_backup_code(db, user, "ABCDE-FGHIJ") is True
        # Second use must fail (marked used)
        assert consume_backup_code(db, user, "ABCDE-FGHIJ") is False

    def test_consume_backup_code_rejects_other_users_code(self, app_module, db, make_user):
        """Bob's backup code shouldn't validate for Alice."""
        import models
        from auth_utils import hash_backup_code, consume_backup_code

        alice = make_user("alice")
        bob = make_user("bob")
        db.add(models.BackupCode(user_id=bob.id, code_hash=hash_backup_code("BOBBO-CODES")))
        db.commit()

        assert consume_backup_code(db, alice, "BOBBO-CODES") is False

    def test_consume_backup_code_with_no_codes(self, app_module, db, make_user):
        from auth_utils import consume_backup_code
        u = make_user("alice")
        assert consume_backup_code(db, u, "ANYTH-INGYY") is False


# ---------- Bootstrap ----------

class TestSeedInitialAdmin:

    def test_seed_creates_admin_when_none_exists(self, app_module, db):
        """The fixture already runs seed once at boot; we wipe and re-run."""
        import models
        from auth_utils import seed_initial_admin
        from roles import Role

        # Wipe existing admin
        db.query(models.User).delete()
        db.commit()

        seed_initial_admin("new_admin", "secret_pw_456")
        admin = db.query(models.User).filter(models.User.role == Role.ADMIN).first()
        assert admin is not None
        assert admin.username == "new_admin"

    def test_seed_is_idempotent(self, app_module, db):
        """Re-seeding when an admin already exists is a no-op."""
        import models
        from auth_utils import seed_initial_admin
        from roles import Role

        before_count = db.query(models.User).filter(models.User.role == Role.ADMIN).count()
        seed_initial_admin("would_be_new_admin", "another_pw")
        after_count = db.query(models.User).filter(models.User.role == Role.ADMIN).count()
        assert after_count == before_count
        # Original seeded admin is still there
        assert db.query(models.User).filter(models.User.username == "would_be_new_admin").first() is None
