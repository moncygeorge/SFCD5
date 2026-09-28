SFCD Sunday School 1.3 - SMS Forgot Password

Upload/replace on the sunday-school branch:
- sunday_school.py
- templates/sunday_school/login.html
- templates/sunday_school/forgot_password.html
- templates/sunday_school/verify_reset_code.html
- templates/sunday_school/reset_password.html
- templates/sunday_school/dashboard.html
- templates/sunday_school/change_password.html

This uses Twilio Verify already configured by SFCD5 through:
TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN
TWILIO_VERIFY_SERVICE_SID

No Twilio secret is stored in GitHub.

Flow:
Login -> Forgot Password -> username -> SMS code -> verify code -> new password.

Security:
- Public response does not disclose whether the username exists.
- Only active Director accounts are eligible in this version.
- Phone is normalized to a US +1 number.
- Twilio Verify controls code expiration/verification.
- New password is stored as a Werkzeug hash.
- Recovery session state is cleared after successful reset.

Before deployment verify the Director profile has a mobile phone number.

Deploy:
cd /home/ubuntu/SFCD5
git pull origin sunday-school
python3 -m py_compile sunday_school.py app.py
sudo systemctl restart sfcd5
sudo systemctl status sfcd5 --no-pager

Test:
https://app.sharondallas.org/sunday-school/login
Click Forgot Password.
