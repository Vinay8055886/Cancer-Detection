import os
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, session, send_from_directory
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from datetime import datetime
from assistant import Assistant
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
import requests

UPLOAD_FOLDER = 'uploads'
MODEL_FOLDER = 'models'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET', 'change-this-secret')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024

# Mail config (example for Gmail SMTP)
app.config.update(
    MAIL_SERVER=os.environ.get('MAIL_SERVER', 'smtp.gmail.com'),
    MAIL_PORT=int(os.environ.get('MAIL_PORT', 587)),
    MAIL_USE_TLS=True,
    MAIL_USERNAME=os.environ.get('EMAIL_USER'),
    MAIL_PASSWORD=os.environ.get('EMAIL_PASS'),
)

db = SQLAlchemy(app)
mail = Mail(app)
s = URLSafeTimedSerializer(app.config['SECRET_KEY'])
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(40), nullable=True)
    verified = db.Column(db.Boolean, default=False)
    role = db.Column(db.String(30), default='patient')  # 'patient' or 'doctor' or 'admin'

class Prediction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    image_path = db.Column(db.String(300))
    result = db.Column(db.String(300))
    probability = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    patient_name = db.Column(db.String(200))
    phone = db.Column(db.String(50))
    language = db.Column(db.String(10), default='en')
    datetime = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50), default='booked')
    hospital_reference = db.Column(db.String(200), nullable=True)

with app.app_context():
    db.create_all()

assistant = Assistant(app=app, db=db)

# helpers
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        phone = request.form.get('phone')
        if User.query.filter_by(username=username).first() or User.query.filter_by(email=email).first():
            flash('User or email exists', 'error')
            return redirect(url_for('register'))
        hashed = generate_password_hash(password)
        user = User(username=username, email=email, password=hashed, phone=phone)
        db.session.add(user)
        db.session.commit()
        # send verification email
        token = s.dumps(email, salt='email-confirm')
        verify_url = url_for('confirm_email', token=token, _external=True)
        msg = Message("Verify your account", recipients=[email])
        msg.body = f'Hi {username}, click to verify your account: {verify_url}'
        try:
            mail.send(msg)
        except Exception as e:
            print('Mail send failed:', e)
        flash('Registered — check your email for verification link', 'info')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/confirm/<token>')
def confirm_email(token):
    try:
        email = s.loads(token, salt='email-confirm', max_age=3600*24)
    except Exception:
        flash('Verification link invalid or expired', 'error')
        return redirect(url_for('index'))
    user = User.query.filter_by(email=email).first()
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('index'))
    user.verified = True
    db.session.commit()
    flash('Email verified. You can log in now.', 'success')
    return redirect(url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter((User.username==username)|(User.email==username)).first()
        if user and check_password_hash(user.password, password):
            if not user.verified:
                flash('Please verify your email before logging in.', 'warning')
                return redirect(url_for('login'))
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid credentials', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    preds = Prediction.query.filter_by(user_id=current_user.id).order_by(Prediction.created_at.desc()).limit(25).all()
    appts = Appointment.query.filter_by(user_id=current_user.id).order_by(Appointment.created_at.desc()).limit(25).all()
    return render_template('dashboard.html', preds=preds, appts=appts)

# admin dashboard for doctors
@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.role not in ('doctor','admin'):
        flash('Access denied', 'error')
        return redirect(url_for('dashboard'))
    appts = Appointment.query.order_by(Appointment.created_at.desc()).limit(200).all()
    preds = Prediction.query.order_by(Prediction.created_at.desc()).limit(200).all()
    return render_template('admin.html', appts=appts, preds=preds)

# upload model
@app.route('/upload_model', methods=['POST'])
@login_required
def upload_model():
    if current_user.role not in ('doctor','admin'):
        return jsonify({'error':'not allowed'}), 403
    f = request.files.get('model_file')
    if not f:
        return jsonify({'error':'no file sent'}), 400
    filename = secure_filename(f.filename)
    os.makedirs(MODEL_FOLDER, exist_ok=True)
    save_path = os.path.join(MODEL_FOLDER, filename)
    f.save(save_path)
    try:
        assistant.load_keras_model(save_path)
    except Exception as e:
        return jsonify({'error':str(e)}), 500
    return jsonify({'ok':True, 'path': save_path})

# server-side prediction
@app.route('/predict_server', methods=['POST'])
@login_required
def predict_server():
    if 'image' not in request.files:
        return jsonify({'error':'no image'}), 400
    f = request.files['image']
    if f.filename == '' or not allowed_file(f.filename):
        return jsonify({'error':'bad file'}), 400
    img_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(f.filename))
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    f.save(img_path)
    from PIL import Image
    img = Image.open(img_path).convert('RGB')
    try:
        res = assistant.predict_image(img)
    except Exception as e:
        return jsonify({'error':str(e)}), 500
    # save prediction
    p = Prediction(user_id=current_user.id, image_path=img_path, result=res.get('label'), probability=res.get('probability',0.0))
    db.session.add(p)
    db.session.commit()
    # trigger booking workflow if cancerous
    if res.get('label','').lower() in assistant.cancer_labels and res.get('probability',0) >= assistant.booking_threshold:
        appt = assistant.create_appointment_for_user(current_user, phone=current_user.phone or request.form.get('phone'), language=request.form.get('language','en'))
        # send to hospital API
        try:
            hospital_resp = assistant.send_to_hospital_api(appt)
            appt.hospital_reference = hospital_resp.get('reference') if isinstance(hospital_resp, dict) else None
        except Exception as e:
            print('Hospital API failed:', e)
        db.session.add(appt)
        db.session.commit()
        # trigger multilingual call and WhatsApp
        assistant.trigger_appointment_call(appt)
        assistant.send_whatsapp_notification(appt)
    return jsonify(res)

@app.route('/history')
@login_required
def history():
    preds = Prediction.query.filter_by(user_id=current_user.id).order_by(Prediction.created_at.desc()).limit(100).all()
    out = [{'id':p.id,'result':p.result,'probability':p.probability,'created_at':p.created_at.isoformat()} for p in preds]
    return jsonify(out)

# serve models
@app.route('/models/<path:fname>')
def serve_model_file(fname):
    return send_from_directory('models', fname)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
