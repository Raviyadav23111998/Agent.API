-- V017: OTP storage for the Challenge / ForgotPassword flows.
-- OTPs are stored HASHED (sha256(user_code:otp)) — a DB leak must not
-- expose live reset codes. Single-use, short expiry, attempt-capped.

CREATE TABLE IF NOT EXISTS ag_auth.password_otps (
    otp_id      SERIAL PRIMARY KEY,
    user_id     INT NOT NULL REFERENCES ag_auth.users(user_id) ON DELETE CASCADE,
    otp_hash    TEXT NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    used        BOOLEAN NOT NULL DEFAULT FALSE,
    attempts    INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT ag_common.utc_now()
);

CREATE INDEX IF NOT EXISTS idx_password_otps_user
    ON ag_auth.password_otps(user_id, created_at DESC);
