# iadroc

AI-based Asynchronous Data Processor example using Flask and SQLite.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
flask --app app.py initdb  # reset DB and create demo users
```

## Running

```bash
FLASK_APP=app.py flask run
```

Access the application at `http://localhost:5000/?token=demo` for the analyst user or `http://localhost:5000/?token=maxiasuper` for the supervisor.

The supervisor dashboard lists the history of all jobs with controls to approve,
reject or cancel them.

The configuration file must include the OpenAI API key, model parameters, the CSV delimiter and how often to create snapshots. The app uses OpenAI's JSON mode to enforce structured responses, so make sure you have a recent `openai` package installed. See `config.json` for an example of the expected format.
