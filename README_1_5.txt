SFCD Sunday School 1.5 - Online Quiz Builder

NEW
- Enforces one teacher -> maximum one class in Director assignment routes.
- Teacher quiz dashboard.
- Create draft quiz.
- Multiple Choice A-D questions.
- True/False questions.
- Points per question.
- Preview.
- Publish / unpublish.
- Delete question and quiz.
- Teacher authorization: teachers can manage only their own quizzes.
- SQLite tables are created automatically at application startup.

UPLOAD TO sunday-school BRANCH
1. sunday_school.py
2. templates/sunday_school/teacher_class.html
3. templates/sunday_school/teacher_quizzes.html
4. templates/sunday_school/create_quiz.html
5. templates/sunday_school/edit_quiz.html
6. templates/sunday_school/preview_quiz.html

DEPLOY
cd /home/ubuntu/SFCD5
git pull origin sunday-school
python3 -m py_compile app.py sunday_school.py
sudo systemctl restart sfcd5
sudo systemctl status sfcd5 --no-pager

TEST
Teacher login -> class -> Manage Quizzes -> Create New Quiz.
Create a draft, add MCQ/True-False questions, preview, publish.

Student quiz-taking and automatic scoring are intentionally NOT included in 1.5.
That will be the next phase.
