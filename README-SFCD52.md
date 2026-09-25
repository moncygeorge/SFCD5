# SFCD 5.2 — Member Home (Phase 1)

This upgrade is intentionally additive. It does **not** replace the election, Twilio OTP, voter management, RSVP, announcements, events, gallery, or admin routes.

## What changes
- `/` becomes a member-facing church home page.
- It displays up to 3 latest announcements, 3 upcoming events, 3 latest gallery photos, latest election status, and the next active RSVP event.
- Existing links continue to use `/announcements`, `/events`, `/gallery`, `/election`, and `/rsvp/<id>`.

## Safe installation
1. Commit/push your current working SFCD5 first.
2. Create a development branch: `git checkout -b sfcd5.2-member-home`
3. Unzip this package.
4. From your SFCD5 repository root run:
   `python3 /path/to/SFCD5.2-member-home/install_sfcd52.py`
5. Review: `git diff`
6. Test locally or on a non-production copy before merging/deploying.

The installer creates an `app.py.pre-sfcd52-<timestamp>.bak` backup and refuses to modify app.py if the expected current `/` route is not found.

## Production deployment after testing
After committing and merging the tested branch to `main`, on Lightsail:

    cd /home/ubuntu/SFCD5
    git pull origin main
    sudo systemctl restart sfcd5
    sudo systemctl status sfcd5 --no-pager

Then test `/`, `/election`, `/admin_dashboard`, `/announcements`, `/events`, `/gallery`, and an RSVP link.

## Next phase
Prayer requests/prayer wall should be implemented separately because it requires explicit privacy/visibility controls.
