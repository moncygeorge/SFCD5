# SFCD 5.1 - Twilio Verify SMS OTP

Required environment variables:
- TWILIO_ACCOUNT_SID
- TWILIO_AUTH_TOKEN
- TWILIO_VERIFY_SERVICE_SID

The application:
- accepts a 10-digit U.S. voter phone number,
- matches common stored formats (10-digit, +1, or leading 1),
- sends the OTP through Twilio Verify,
- verifies the code with Twilio,
- authenticates the voter once for the election session,
- rate-limits resend attempts from the same browser to 30 seconds,
- never stores the OTP or Twilio credentials in the database/GitHub,
- logs OTP send/approval/failure events without logging the code.

Trial Twilio accounts can only send to recipients allowed by Twilio trial restrictions.
