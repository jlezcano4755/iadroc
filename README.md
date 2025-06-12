# iadroc

AI-based Asynchronous Data Processor example using Flask and SQLite.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
flask --app app.py initdb  # reset DB and create demo users
flask --app app.py create-user alice secret analyst  # add more users
```

## Running

```bash
FLASK_APP=app.py flask run
```

Start the server and open `http://localhost:5000` in your browser. Use the demo
credentials (`demo`/`demo` for the analyst or `super`/`maxiasuper` for the
supervisor) to log in.

The supervisor dashboard lists the history of all jobs with controls to approve,
reject or cancel them.

The configuration file must include the OpenAI API key **encoded in base64**, model parameters, the CSV delimiter and how often to create snapshots.  The prompt for the AI is provided separately in `directive.txt`.  The app uses OpenAI's JSON mode to enforce structured responses, so make sure you have a recent `openai` package installed.  See `config.json` and `directive.txt` for examples of the expected format.
When using JSON mode your prompt must mention the word "json" somewhere.  The application now appends a short reminder automatically if it is missing.

Jobs can optionally include a short description so they are easier to recognize in the dashboard.
When creating a job you must upload three files: the CSV data, the `config.json` settings file and the `directive.txt` file containing the prompt for the AI.

## Docker

Build the Docker image and push it to Docker Hub (replace `youruser` with your username):

```bash
docker build -t youruser/iadroc:latest .
docker push youruser/iadroc:latest
```

Run the container mounting a directory to persist the database and uploads:

```bash
docker run -d -p 5000:5000 \
  -v $PWD/data:/data \
  -e DB_PATH=/data/iadroc.db \
  -e UPLOAD_FOLDER=/data/uploads \
  --name iadroc youruser/iadroc:latest
```

After the container starts, initialize the database and create accounts:

```bash
docker exec iadroc flask initdb
# docker exec iadroc flask create-user <name> <token> <role>
```

Then open `http://localhost:5000` and log in with your credentials.
