SFCD5 Sunday School - Change 1

Upload these files to the sunday-school GitHub branch preserving folders.

Then edit app.py with ONLY these additions:

1) Near imports:
from sunday_school import sunday_school

2) After the Flask app/database initialization:
app.register_blueprint(sunday_school)

Do not replace app.py from this package and do not merge to main yet.

Test URLs after deployment:
/sunday-school/setup
/sunday-school/login
/sunday-school/director
