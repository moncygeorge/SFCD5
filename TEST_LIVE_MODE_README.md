# SFCD5 Election Test / Live Mode

- New elections start in **Test Mode**. Existing elections are migrated to **Live Mode** to protect existing ballots.
- Test ballots are stored in `election_test_votes` and never included in live tallies.
- Admin can reset a registered phone's test votes for one election, across its phases. The voter must complete OTP verification again if not already verified.
- Close the election before activating **Live Mode**. This is irreversible and clears test ballots for that election.
- Live voting continues to use the original anonymous `election_ballots` and `election_voter_status` tables. Test resets never delete from those tables.
- Audit records are written for resets and mode activation.

## Deployment

1. Back up your live SQLite database using SQLite's `.backup` command or Python sqlite3 backup API, plus your existing application files. Confirm `DB_PATH` or `DATA_DIR` before doing so.
2. Upload the updated repository files to the `sunday-school` branch on GitHub. **Do not upload a production SQLite database.**
3. On Lightsail, preserve any local changes before fetching the branch. Update your checkout to the desired commit.
4. Run `python3 -m py_compile app.py sunday_school.py ministry_roles.py` using the service's Python environment.
5. Restart `sfcd5.service`, check `systemctl status sfcd5`, then `curl -f http://127.0.0.1:8001/health`.
6. Create a new election, open a phase, test a vote, reset the test phone, vote again, close the election, switch to Live Mode, and confirm the live tally starts at zero.

**Security:** This follows the app's existing admin session checks. Before using with real elections, add CSRF protection to admin POST forms and conduct end-to-end acceptance tests. The mode switch is intentionally one-way.
