# SFCD 5.1 Voting Hardening

Implemented:
- Duplicate candidate detection before database writes.
- SQLite 15-second busy timeout and safer transactions.
- Responsive multi-column ballot UI.
- Election audit log (`election_audit`) that records administrative/session activity and ballot acceptance without recording candidate selection.
- Backup script: `scripts/backup_sfcd.sh`.
- Existing OTP flow remains available in test/log mode.

Authentication:
- Current OTP generator/verification is retained.
- For production SMS, replace `send_election_otp()` with an SMS provider and keep credentials in environment variables, never GitHub.
- A no-cost voter PIN mode should be added only after deciding how PINs will be securely distributed/reset; do not store plaintext PINs.

Recommended Lightsail backup cron:
`0 3 * * * /home/ubuntu/SFCD5/scripts/backup_sfcd.sh >> /home/ubuntu/sfcd5-backup.log 2>&1`

Before production:
1. Test 20+ candidate phase creation.
2. Test duplicate names.
3. Test simultaneous votes.
4. Test phase deletion while closed.
5. Verify backups restore successfully.
