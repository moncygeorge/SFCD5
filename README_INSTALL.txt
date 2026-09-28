SFCD Sunday School 1.2 - Director Change Password

This package includes the Teacher Management changes from 1.1 PLUS Director Change Password.

Replace/upload these files to the sunday-school branch:
1. sunday_school.py
2. templates/sunday_school/dashboard.html
3. templates/sunday_school/change_password.html

Do NOT replace app.py.
Do NOT replace login.html or setup.html.

Change Password behavior:
- Director must already be logged in.
- Requires current password.
- New password must be at least 8 characters.
- New password and confirmation must match.
- Stores only a Werkzeug password hash.
- Does not change classes, teachers, or other Sunday School data.

IMPORTANT FOR THE CURRENT DIRECTOR:
If the current stored password hash does not match the password the Director knows, the new Change Password page cannot repair that by itself because it correctly requires the current password. Perform a one-time administrator reset of that Director password first, then future changes can be made through the website.

Deployment:
cd /home/ubuntu/SFCD5
git pull origin sunday-school
python3 -m py_compile sunday_school.py app.py
sudo systemctl restart sfcd5
sudo systemctl status sfcd5 --no-pager
