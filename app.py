import os
import csv
import json
import threading
from datetime import datetime
from flask import Flask, request, jsonify, render_template, redirect, url_for
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///iadroc.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
db = SQLAlchemy(app)

# --------------------
# Database models
# --------------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    token = db.Column(db.String(120), unique=True, nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'analyst' or 'supervisor'

class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    csv_path = db.Column(db.String(200), nullable=False)
    config_path = db.Column(db.String(200), nullable=False)
    # possible states: pending, approved, processing, done, failed
    status = db.Column(db.String(20), default="pending")
    token_estimate = db.Column(db.Integer)
    tokens_used = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# --------------------
# Helper functions
# --------------------

def get_user_from_token(token: str):
    if not token:
        return None
    return User.query.filter_by(token=token).first()

def validate_config(config: dict):
    required_keys = ['retry_times', 'max_rows', 'model', 'target', 'new_columns']
    return all(key in config for key in required_keys)

def analyze_csv(csv_path: str, target: str):
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        if target not in reader.fieldnames:
            return False, None
        for row in reader:
            text = row.get(target)
            if text and text.strip():
                return True, text  # return first non-empty row text
    return False, None

def token_estimator(text: str) -> int:
    return len(text.split())  # naive token estimate

def placeholder_process(row: dict, config: dict) -> dict:
    # Simulate model output by appending a new column with text length
    result = row.copy()
    for col in config.get('new_columns', {}):
        result[col] = len(row.get(config['target'], ''))
    return result

def process_job_async(job_id: int):
    job = Job.query.get(job_id)
    if not job:
        return
    job.status = 'processing'
    db.session.commit()

    # Load config
    with open(job.config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    processed_rows = []
    try:
        with open(job.csv_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            count = 0
            for row in reader:
                if config['max_rows'] and count >= config['max_rows']:
                    break
                result = placeholder_process(row, config)
                processed_rows.append(result)
                count += 1
        # For this simple app we won't write output, just simulate tokens_used
        job.tokens_used = sum(token_estimator(row[config['target']]) for row in processed_rows)
        job.status = 'done'
    except Exception as e:
        job.status = 'failed'
    db.session.commit()

# --------------------
# Routes
# --------------------

@app.route('/')
def index():
    token = request.args.get('token')
    user = get_user_from_token(token)
    if not user:
        return 'Unauthorized', 401
    jobs = Job.query.filter_by(user_id=user.id).all()
    return render_template('index.html', user=user, jobs=jobs, token=token)

@app.route('/verify', methods=['POST'])
def verify_files():
    token = request.form.get('token')
    user = get_user_from_token(token)
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    csv_file = request.files.get('csv')
    config_file = request.files.get('config')
    if not csv_file or not config_file:
        return jsonify({'error': 'Missing files'}), 400

    csv_path = os.path.join(app.config['UPLOAD_FOLDER'], f'tmp_{csv_file.filename}')
    config_path = os.path.join(app.config['UPLOAD_FOLDER'], f'tmp_{config_file.filename}')
    csv_file.save(csv_path)
    config_file.save(config_path)

    with open(config_path, 'r', encoding='utf-8') as f:
        try:
            config = json.load(f)
        except json.JSONDecodeError:
            return jsonify({'error': 'Invalid config JSON'}), 400

    if not validate_config(config):
        return jsonify({'error': 'Config missing required fields'}), 400

    ok, sample_text = analyze_csv(csv_path, config['target'])
    if not ok:
        return jsonify({'error': 'CSV missing target column or no valid rows'}), 400

    token_est = token_estimator(sample_text)
    return jsonify({'message': 'verified', 'token_estimate': token_est})

@app.route('/jobs', methods=['POST'])
def create_job():
    token = request.form.get('token')
    user = get_user_from_token(token)
    if not user:
        return 'Unauthorized', 401

    csv_file = request.files.get('csv')
    config_file = request.files.get('config')
    token_estimate = request.form.get('token_estimate')

    if not all([csv_file, config_file, token_estimate]):
        return 'Missing data', 400

    csv_path = os.path.join(app.config['UPLOAD_FOLDER'], f'{datetime.utcnow().timestamp()}_{csv_file.filename}')
    config_path = os.path.join(app.config['UPLOAD_FOLDER'], f'{datetime.utcnow().timestamp()}_{config_file.filename}')
    csv_file.save(csv_path)
    config_file.save(config_path)

    job = Job(user_id=user.id, csv_path=csv_path, config_path=config_path, token_estimate=int(token_estimate))
    db.session.add(job)
    db.session.commit()

    return redirect(url_for('index', token=token))

@app.route('/jobs/<int:job_id>/approve', methods=['POST'])
def approve_job(job_id):
    token = request.form.get('token')
    user = get_user_from_token(token)
    if not user or user.role != 'supervisor':
        return 'Forbidden', 403

    job = Job.query.get_or_404(job_id)
    job.status = 'approved'
    db.session.commit()

    threading.Thread(target=process_job_async, args=(job.id,)).start()

    return redirect(url_for('index', token=token))

@app.route('/jobs/<int:job_id>')
def job_status(job_id):
    token = request.args.get('token')
    user = get_user_from_token(token)
    if not user:
        return 'Unauthorized', 401
    job = Job.query.get_or_404(job_id)
    if job.user_id != user.id and user.role != 'supervisor':
        return 'Forbidden', 403
    return jsonify({
        'id': job.id,
        'status': job.status,
        'token_estimate': job.token_estimate,
        'tokens_used': job.tokens_used,
    })

# --------------------
# Command to initialize DB with a sample analyst and supervisor
# --------------------

@app.cli.command('initdb')
def initdb():
    db.create_all()
    if not User.query.first():
        analyst = User(name='analyst1', token='analyst-token', role='analyst')
        supervisor = User(name='super1', token='super-token', role='supervisor')
        db.session.add_all([analyst, supervisor])
        db.session.commit()
        print('Initialized database with sample users.')
    else:
        print('Database already initialized.')

if __name__ == '__main__':
    app.run(debug=True)
