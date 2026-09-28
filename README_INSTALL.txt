SFCD Sunday School 1.1 - Teacher Management

REPLACES:
1. sunday_school.py
2. templates/sunday_school/dashboard.html

DO NOT replace app.py.
DO NOT replace setup.html or login.html.

New features:
- Director creates teacher accounts
- Name, username, email, phone, temporary password
- Assign teacher to one or more active classes
- Change teacher/class assignments
- Activate/deactivate teacher
- Reset teacher password
- Teacher count on Director dashboard

The database migration is automatic: sunday_school_teacher_classes is created with CREATE TABLE IF NOT EXISTS.

After copying files to C:\Users\moncy\SFCD5:
  git checkout sunday-school
  git add sunday_school.py templates/sunday_school/dashboard.html
  git commit -m "Add Sunday School teacher management"
  git pull --rebase origin sunday-school
  git push origin sunday-school

On Lightsail:
  cd /home/ubuntu/SFCD5
  git pull origin sunday-school
  python3 -m py_compile sunday_school.py app.py
  sudo systemctl restart sfcd5
  sudo systemctl status sfcd5 --no-pager
