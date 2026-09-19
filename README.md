# SFCD5 — Lightsail Church Portal

SFCD5 is a separate copy of SFCD4. It adds reusable voting-event links while keeping the existing SFCD4 RSVP and legacy voting routes intact.

## Important compatibility
- Existing dynamic RSVP route remains `/rsvp/<event_id>` (including `/rsvp/2`).
- Existing `/vote` legacy ballot remains available.
- Existing database schema is extended only with new tables; existing RSVP/voter/vote tables are not deleted.

## New SFCD5 voting workflow
1. Admin logs in at `/admin_login`.
2. Open `/admin_dashboard`.
3. Under **Create Voting Link**, enter a title, question/position, and choices (one per line).
4. A public link is generated as `/vote/<event_id>`.
5. Add authorized voter phone numbers in the Voters section.
6. Open voting from the dashboard.
7. Voters authenticate with their authorized phone number and can vote once per ballot.
8. Admin can view tally/results at `/admin/voting/<event_id>`.

## Lightsail data
For a separate SFCD5 test installation, use a separate data directory such as:
`DATA_DIR=/home/ubuntu/sfcd5-data`

Do not point a test SFCD5 instance at the live SFCD4 database unless you intentionally want them to share data.

## Deployment safety
Run SFCD5 on a different port/service while testing. Do not replace the live SFCD4 Nginx upstream until SFCD5 has passed smoke tests.
