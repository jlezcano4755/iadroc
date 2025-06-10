# iadroc

AI-based Asynchronous Data Processor example using Flask and SQLite.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
flask --app app.py initdb  # create demo users
```

## Running

```bash
FLASK_APP=app.py flask run
```

Access the application at `http://localhost:5000/?token=demo` for the analyst user or `http://localhost:5000/?token=maxiasuper` for the supervisor.
