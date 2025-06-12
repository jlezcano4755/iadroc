import os
import csv
import json
import threading
import time
import shutil
import random
import base64
import openai
from datetime import datetime
from flask import Flask, request, jsonify, render_template, redirect, url_for, send_file
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
    user = db.relationship('User', backref='jobs')
    csv_path = db.Column(db.String(200), nullable=False)
    config_path = db.Column(db.String(200), nullable=False)
    directive_path = db.Column(db.String(200), nullable=False)
    config_json = db.Column(db.Text, nullable=False)
    # possible states: pending, approved, processing, done, failed,
    # rejected, cancelled
    status = db.Column(db.String(20), default="pending")
    token_estimate = db.Column(db.Integer)
    token_estimate_prompt = db.Column(db.Integer)
    token_estimate_completion = db.Column(db.Integer)
    tokens_used = db.Column(db.Integer, default=0)
    tokens_prompt_used = db.Column(db.Integer, default=0)
    tokens_completion_used = db.Column(db.Integer, default=0)
    model = db.Column(db.String(100))
    error = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    description = db.Column(db.String(200))
    output_path = db.Column(db.String(200))
    snapshot_path = db.Column(db.String(200))
    rows_processed = db.Column(db.Integer, default=0)
    total_rows = db.Column(db.Integer, default=0)
    error_rows = db.Column(db.Integer, default=0)

# --------------------
# Helper functions
# --------------------

def get_user_from_token(token: str):
    if not token:
        return None
    return User.query.filter_by(token=token).first()

def validate_config(config: dict):
    required_keys = [
        'retry_times', 'max_rows', 'model', 'target', 'new_columns',
        'openai_api_key', 'delimiter', 'snapshot_rows'
    ]
    return all(key in config for key in required_keys)

def ensure_json_hint(text: str) -> str:
    """Ensure the directive mentions JSON to satisfy OpenAI's JSON mode."""
    if 'json' not in text.lower():
        return text.strip() + "\n\nResponde exclusivamente con un objeto JSON."
    return text

def analyze_csv(csv_path: str, target: str, delimiter: str = ','):
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        if target not in reader.fieldnames:
            return False, None
        for row in reader:
            text = row.get(target)
            if text and text.strip():
                return True, text  # return first non-empty row text
    return False, None

def token_estimator(csv_path: str, config: dict, directive: str, sample_size: int = 5) -> dict:
    """Estimate token usage by sampling rows and querying OpenAI."""
    directive = ensure_json_hint(directive)
    delimiter = config.get('delimiter', ',')
    with open(csv_path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f, delimiter=delimiter))

    if not rows:
        return 0

    sample_rows = random.sample(rows, min(sample_size, len(rows)))
    api_key = base64.b64decode(config.get('openai_api_key')).decode()
    client = openai.OpenAI(api_key=api_key)
    total_prompt = 0
    total_completion = 0
    total_tokens = 0
    successful = 0

    for row in sample_rows:
        text = row.get(config['target'], '') or ''
        if not text.strip():
            continue
        retries = config.get('retry_times', 3)
        last_err = None
        for _ in range(retries):
            try:
                resp = client.chat.completions.create(
                    model=config.get('model', 'gpt-3.5-turbo'),
                    messages=[
                        {"role": "system", "content": directive},
                        {"role": "user", "content": text}
                    ],
                    temperature=config.get('temperature', 0.2),
                    max_tokens=config.get('max_tokens', 128),
                    response_format={"type": "json_object"}
                )
                if resp.usage:
                    total_tokens += resp.usage.total_tokens
                    total_prompt += resp.usage.prompt_tokens or 0
                    total_completion += resp.usage.completion_tokens or 0
                    successful += 1
                break
            except Exception as e:
                last_err = e
        else:
            continue

    if successful == 0:
        raise RuntimeError(str(last_err))

    avg_total = total_tokens / successful
    avg_prompt = total_prompt / successful
    avg_completion = total_completion / successful
    return {
        'total': int(avg_total * len(rows)),
        'prompt': int(avg_prompt * len(rows)),
        'completion': int(avg_completion * len(rows))
    }

def openai_process(row: dict, config: dict, directive: str) -> tuple:
    """Process a row with OpenAI and return the updated row and token usage."""
    text = row.get(config['target'], '') or ''
    directive = ensure_json_hint(directive)
    retries = config.get('retry_times', 3)
    api_key = base64.b64decode(config.get('openai_api_key')).decode()
    client = openai.OpenAI(api_key=api_key)
    last_err = None
    for _ in range(retries):
        try:
            resp = client.chat.completions.create(
                model=config.get('model', 'gpt-3.5-turbo'),
                messages=[
                    {"role": "system", "content": directive},
                    {"role": "user", "content": text}
                ],
                temperature=config.get('temperature', 0.2),
                max_tokens=config.get('max_tokens', 128),
                response_format={"type": "json_object"}
            )
            content = resp.choices[0].message.content
            data = json.loads(content)
            for col in config.get('new_columns', []):
                row[col] = data.get(col, '')
            if resp.usage:
                prompt = resp.usage.prompt_tokens or 0
                completion = resp.usage.completion_tokens or 0
            else:
                prompt = completion = 0
            return row, prompt, completion
        except Exception as e:
            last_err = e
    raise RuntimeError(str(last_err))

def process_job_async(job_id: int):
    with app.app_context():
        job = Job.query.get(job_id)
        if not job:
            return
        job.status = 'processing'
        job.error = None
        db.session.commit()

        config = json.loads(job.config_json)
        with open(job.directive_path, 'r', encoding='utf-8') as df:
            directive_text = df.read()
        delimiter = config.get('delimiter', ',')
        snapshot_interval = config.get('snapshot_rows', 100)

        try:
            with open(job.csv_path, newline='', encoding='utf-8') as f:
                reader = list(csv.DictReader(f, delimiter=delimiter))
            job.total_rows = len(reader)
            db.session.commit()

            output_path = os.path.join(os.path.dirname(job.csv_path), 'output.csv')
            with open(output_path, 'w', newline='', encoding='utf-8') as out_f:
                writer = None
                for idx, row in enumerate(reader):
                    if config['max_rows'] and idx >= config['max_rows']:
                        break

                    # wait if paused / stop if cancelled
                    while True:
                        db.session.refresh(job)
                        if job.status == 'cancelled':
                            return
                        if job.status != 'paused':
                            break
                        time.sleep(1)

                    if idx < job.rows_processed:
                        continue

                    try:
                        result, p_used, c_used = openai_process(row, config, directive_text)
                    except Exception:
                        job.error_rows += 1
                        result, p_used, c_used = row, 0, 0

                    if writer is None:
                        writer = csv.DictWriter(out_f, fieldnames=result.keys(), delimiter=delimiter)
                        writer.writeheader()

                    writer.writerow(result)
                    out_f.flush()
                    job.rows_processed = idx + 1
                    job.tokens_used += p_used + c_used
                    job.tokens_prompt_used += p_used
                    job.tokens_completion_used += c_used
                    if job.rows_processed % snapshot_interval == 0:
                        snap = os.path.join(os.path.dirname(job.csv_path), f'snapshot_{job.rows_processed}.csv')
                        shutil.copy(output_path, snap)
                        job.snapshot_path = snap
                    db.session.commit()

        except Exception as e:
            job.status = 'failed'
            job.error = str(e)
        else:
            job.output_path = output_path
            job.snapshot_path = output_path
            job.status = 'done'
        finally:
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
    if user.role == 'supervisor':
        jobs = Job.query.order_by(Job.created_at.desc()).all()
    else:
        jobs = Job.query.filter_by(user_id=user.id).order_by(Job.created_at.desc()).all()
    return render_template('index.html', user=user, jobs=jobs, token=token)

@app.route('/verify', methods=['POST'])
def verify_files():
    token = request.form.get('token')
    user = get_user_from_token(token)
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    csv_file = request.files.get('csv')
    config_file = request.files.get('config')
    directive_file = request.files.get('directive')
    if not csv_file or not config_file or not directive_file:
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

    directive_text = directive_file.read().decode('utf-8')

    if not validate_config(config):
        return jsonify({'error': 'Config missing required fields'}), 400

    ok, _ = analyze_csv(csv_path, config['target'], config.get('delimiter', ','))
    if not ok:
        return jsonify({'error': 'CSV missing target column or no valid rows'}), 400

    try:
        token_est = token_estimator(csv_path, config, directive_text)
    except Exception as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({
        'message': 'verified',
        'token_estimate_total': token_est['total'],
        'token_estimate_prompt': token_est['prompt'],
        'token_estimate_completion': token_est['completion']
    })

@app.route('/jobs', methods=['POST'])
def create_job():
    token = request.form.get('token')
    user = get_user_from_token(token)
    if not user:
        return 'Unauthorized', 401

    csv_file = request.files.get('csv')
    config_file = request.files.get('config')
    directive_file = request.files.get('directive')
    token_estimate = request.form.get('token_estimate')
    token_estimate_prompt = request.form.get('token_estimate_prompt')
    token_estimate_completion = request.form.get('token_estimate_completion')
    description = request.form.get('description')

    if not all([csv_file, config_file, directive_file, token_estimate,
                token_estimate_prompt, token_estimate_completion]):
        return 'Missing data', 400

    # read config file to store json parameters
    config_bytes = config_file.read()
    config_file.seek(0)
    try:
        config_data = json.loads(config_bytes.decode('utf-8'))
    except json.JSONDecodeError:
        return 'Invalid config', 400

    job = Job(
        user_id=user.id,
        token_estimate=int(token_estimate),
        token_estimate_prompt=int(token_estimate_prompt),
        token_estimate_completion=int(token_estimate_completion),
        csv_path='',
        config_path='',
        directive_path='',
        config_json=json.dumps(config_data),
        description=description,
        model=config_data.get('model')
    )
    db.session.add(job)
    db.session.commit()

    job_folder = os.path.join(app.config['UPLOAD_FOLDER'], str(job.id))
    os.makedirs(job_folder, exist_ok=True)
    csv_path = os.path.join(job_folder, csv_file.filename)
    config_path = os.path.join(job_folder, 'config.json')
    directive_path = os.path.join(job_folder, 'directive.txt')
    csv_file.save(csv_path)
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write(config_bytes.decode('utf-8'))
    directive_file.save(directive_path)

    job.csv_path = csv_path
    job.config_path = config_path
    job.directive_path = directive_path
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

@app.route('/jobs/<int:job_id>/reject', methods=['POST'])
def reject_job(job_id):
    token = request.form.get('token')
    user = get_user_from_token(token)
    if not user or user.role != 'supervisor':
        return 'Forbidden', 403

    job = Job.query.get_or_404(job_id)
    job.status = 'rejected'
    db.session.commit()

    return redirect(url_for('index', token=token))

@app.route('/jobs/<int:job_id>/cancel', methods=['POST'])
def cancel_job(job_id):
    token = request.form.get('token')
    user = get_user_from_token(token)
    if not user or user.role != 'supervisor':
        return 'Forbidden', 403

    job = Job.query.get_or_404(job_id)
    if job.status in ['approved', 'processing']:
        job.status = 'cancelled'
        db.session.commit()

    return redirect(url_for('index', token=token))

@app.route('/jobs/<int:job_id>/pause', methods=['POST'])
def pause_job(job_id):
    token = request.form.get('token')
    user = get_user_from_token(token)
    if not user or user.role != 'supervisor':
        return 'Forbidden', 403

    job = Job.query.get_or_404(job_id)
    if job.status == 'processing':
        job.status = 'paused'
        db.session.commit()

    return redirect(url_for('index', token=token))

@app.route('/jobs/<int:job_id>/resume', methods=['POST'])
def resume_job(job_id):
    token = request.form.get('token')
    user = get_user_from_token(token)
    if not user or user.role != 'supervisor':
        return 'Forbidden', 403

    job = Job.query.get_or_404(job_id)
    if job.status == 'paused':
        job.status = 'processing'
        db.session.commit()

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
        'model': job.model,
        'token_estimate': job.token_estimate,
        'token_estimate_prompt': job.token_estimate_prompt,
        'token_estimate_completion': job.token_estimate_completion,
        'tokens_used': job.tokens_used,
        'tokens_prompt_used': job.tokens_prompt_used,
        'tokens_completion_used': job.tokens_completion_used,
        'error': job.error,
        'rows_processed': job.rows_processed,
        'total_rows': job.total_rows,
        'error_rows': job.error_rows,
    })

@app.route('/jobs/<int:job_id>/output')
def job_output(job_id):
    token = request.args.get('token')
    user = get_user_from_token(token)
    if not user:
        return 'Unauthorized', 401
    job = Job.query.get_or_404(job_id)
    if job.user_id != user.id and user.role != 'supervisor':
        return 'Forbidden', 403
    if job.status != 'done' or not job.output_path or not os.path.exists(job.output_path):
        return 'No output available', 404
    return send_file(job.output_path, as_attachment=True)

@app.route('/jobs/<int:job_id>/snapshot')
def job_snapshot(job_id):
    token = request.args.get('token')
    user = get_user_from_token(token)
    if not user:
        return 'Unauthorized', 401
    job = Job.query.get_or_404(job_id)
    if job.user_id != user.id and user.role != 'supervisor':
        return 'Forbidden', 403
    if not job.snapshot_path or not os.path.exists(job.snapshot_path):
        return 'No snapshot available', 404
    return send_file(job.snapshot_path, as_attachment=True)

# --------------------
# Command to initialize DB with a sample analyst and supervisor
# --------------------

@app.cli.command('initdb')
def initdb():
    if os.path.exists('iadroc.db'):
        os.remove('iadroc.db')
    shutil.rmtree(app.config['UPLOAD_FOLDER'], ignore_errors=True)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    db.create_all()
    analyst = User(name='demo', token='demo', role='analyst')
    supervisor = User(name='super', token='maxiasuper', role='supervisor')
    db.session.add_all([analyst, supervisor])
    db.session.commit()
    print('Database reset with demo users.')

if __name__ == '__main__':
    app.run(debug=True)
