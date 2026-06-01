# Teachable Cancer Detection — Full-featured Flask App

This project includes:
- Server-side Keras (.h5) model inference
- User auth with hashed passwords and email verification
- Multilingual TTS notifications (gTTS)
- Twilio SMS and WhatsApp notifications
- Hospital API integration (configurable endpoint)
- Admin dashboard for doctors to upload models and view appointments
- Google Calendar integration optionally (see earlier notes)

## Setup (local)

1. Clone / unzip the project.
2. Create virtualenv and install:
   ```
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. Create environment variables (example):
   ```
   export FLASK_SECRET='change-me'
   export EMAIL_USER='you@gmail.com'
   export EMAIL_PASS='app-password'
   export TWILIO_SID='ACxxxxx'
   export TWILIO_TOKEN='xxxxx'
   export TWILIO_FROM='+1XXXX'            # SMS capable
   export TWILIO_WHATSAPP_FROM='whatsapp:+1415XXXX'  # Twilio sandbox number
   export HOSPITAL_API='https://hospital.example.com/api/book'  # optional
   ```

4. Run:
   ```
   flask run
   ```
   Open http://localhost:5000

## How it works

- Doctors/admin upload a Keras `.h5` model via the admin dashboard.
- Patients register and verify email, then upload images for server-side analysis.
- If detection meets criteria, the system:
  - Creates an Appointment record
  - Attempts to POST appointment to the configured HOSPITAL_API
  - Sends multilingual TTS (gTTS) audio saved on server; and sends SMS via Twilio
  - Sends WhatsApp notification via Twilio (must be enabled for your Twilio account)

## Notes & Security
- Passwords are hashed; however use stronger auth (2FA) in production.
- For Twilio voice calls that play audio, you must host the audio over HTTPS so Twilio can fetch it.
- Hospital API endpoints must be secure (HTTPS) and require authentication — implement API keys or OAuth.
- Use HTTPS in production, set SECRET_KEY to a secure random value, and secure environment variables.

## Deploying as a real website
- Use Render, Railway, Heroku, or Docker on any cloud provider.
- Provide environment variables in the platform settings.
- Make sure the server can accept file uploads and has enough memory for TensorFlow model loading.
- Use a production WSGI server like Gunicorn:
  ```
  gunicorn app:app --workers 3
  ```

