SFCD Sunday School 1.4 - Teacher Portal

Built on Sunday School 1.3.

NEW:
- Teacher login
- Teacher dashboard
- Teacher sees only assigned active classes
- Server-side authorization prevents opening an unassigned class by changing the URL
- Teacher class page
- Teacher change password
- Teacher logout

No new database is required. Existing sunday_school_users and
sunday_school_teacher_classes are reused.

UPLOAD TO sunday-school BRANCH:
- sunday_school.py
- templates/sunday_school/teacher_login.html
- templates/sunday_school/teacher_dashboard.html
- templates/sunday_school/teacher_class.html
- templates/sunday_school/teacher_change_password.html

The ZIP also contains the existing 1.3 templates for completeness.

DEPLOY:
cd /home/ubuntu/SFCD5
git pull origin sunday-school
python3 -m py_compile app.py sunday_school.py
sudo systemctl restart sfcd5
sudo systemctl status sfcd5 --no-pager

TEST:
Director creates a teacher with a temporary password and assigns at least one class.
Teacher login:
https://app.sharondallas.org/sunday-school/teacher/login

The teacher should see only classes assigned by the Director.
