from project import create_app

from project.extension import db

from project.model import User

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        # This looks at the imported 'User' model and creates the table in MySQL
        db.create_all()
        print("Connected to MySQL and tables created!")
    app.run(debug=True)