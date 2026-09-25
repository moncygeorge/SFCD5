# SFCD 5.2 – Member Home

This package is an additive upgrade for the existing SFCD5 application.

## What it changes

- Replaces only the `/` route behavior.
- `/` becomes a member-facing church home page.
- Reads from the existing:
  - `announcements`
  - `events`
  - `gallery`
  - `election_sessions`
  tables.
- Links members to the existing `/election`, `/announcements`, `/events`, and `/gallery` routes.

## What it does NOT change

- Twilio Verify / OTP authentication
- Phased election logic
- Ballots or results
- Voter management
- Admin dashboard
- RSVP routes
- Existing announcement/event/gallery administration
- Database schema

## Installation on a TEST branch/server

From the repository root:

```bash
python install_sfcd52.py
python -m py_compile app.py
```

Do not run the installer on production until the branch has been reviewed/tested.

The installer creates `app.py.sfcd51.backup` before modifying `app.py`.
