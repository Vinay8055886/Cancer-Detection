import os, tempfile, json
from tensorflow.keras.models import load_model
import numpy as np
from PIL import Image
from gtts import gTTS
from twilio.rest import Client
from datetime import datetime
import requests

class Assistant:
    def __init__(self, app=None, db=None):
        self.app = app
        self.db = db
        self.keras_model = None
        self.input_size = (224,224)
        self.cancer_labels = {'cancerous','malignant','positive'}
        self.booking_threshold = 0.5
        # Twilio / WhatsApp config
        self.twilio_sid = os.environ.get('TWILIO_SID')
        self.twilio_token = os.environ.get('TWILIO_TOKEN')
        self.twilio_from = os.environ.get('TWILIO_FROM')  # SMS number
        self.twilio_whatsapp_from = os.environ.get('TWILIO_WHATSAPP_FROM')  # e.g. 'whatsapp:+1415XXXX'
        # Hospital API endpoint
        self.hospital_api = os.environ.get('HOSPITAL_API')  # e.g. https://hospital.example.com/api/book
        # Google Calendar token check handled in app or separate flow
        self.tts_host = os.environ.get('TTS_HOST')  # Optional: host to upload generated tts audio
        # HTTP session
        self.session = requests.Session()

    def load_keras_model(self, path):
        self.keras_model = load_model(path)
        try:
            inp = self.keras_model.input_shape
            if len(inp) >= 3:
                h = inp[1] or 224
                w = inp[2] or 224
                self.input_size = (int(h), int(w))
        except Exception:
            pass
        return True

    def preprocess(self, pil_img):
        img = pil_img.resize(self.input_size)
        arr = np.array(img).astype('float32') / 255.0
        if arr.ndim == 3:
            arr = np.expand_dims(arr, 0)
        return arr

    def predict_image(self, pil_img):
        if not self.keras_model:
            raise RuntimeError('No Keras model loaded')
        x = self.preprocess(pil_img)
        preds = self.keras_model.predict(x)[0]
        top_idx = int(np.argmax(preds))
        prob = float(preds[top_idx])
        label = f'class_{top_idx}'
        # If model attached metadata mapping, integrate here
        return {'label': label, 'probability': prob, 'index': top_idx}

    def create_appointment_for_user(self, user, phone=None, language='en'):
        from app import Appointment
        appt = Appointment(user_id=user.id if user else None,
                           patient_name=user.username if user else 'Unknown',
                           phone=phone or '',
                           language=language,
                           datetime=datetime.utcnow().isoformat(),
                           status='booked')
        return appt

    def send_to_hospital_api(self, appt):
        if not self.hospital_api:
            raise RuntimeError('No HOSPITAL_API configured')
        payload = {
            'patient_name': appt.patient_name,
            'phone': appt.phone,
            'language': appt.language,
            'datetime': appt.datetime
        }
        resp = self.session.post(self.hospital_api, json=payload, timeout=10)
        try:
            return resp.json()
        except Exception:
            return {'status': resp.status_code, 'text': resp.text}

    def trigger_appointment_call(self, appointment):
        # create multilingual TTS and attempt to make a call (or fallback to SMS)
        text = f"Hello {appointment.patient_name}. Our system detected a potentially cancerous result and booked an appointment on {appointment.datetime}. Please contact the hospital to confirm."
        lang = appointment.language or 'en'
        # use gTTS to create audio
        try:
            tts = gTTS(text=text, lang=lang)
            tmpf = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
            tts.save(tmpf.name)
            # If Twilio available, send SMS and optionally call
            if self.twilio_sid and self.twilio_token and self.twilio_from and appointment.phone:
                client = Client(self.twilio_sid, self.twilio_token)
                # send SMS as notification
                try:
                    client.messages.create(
                        body=f'Appointment booked for {appointment.patient_name} at {appointment.datetime}',
                        from_=self.twilio_from,
                        to=appointment.phone
                    )
                except Exception as e:
                    print('Twilio SMS failed:', e)
            else:
                print('Twilio not configured; tts file at', tmpf.name)
        except Exception as e:
            print('TTS failed:', e)

    def send_whatsapp_notification(self, appointment):
        if not (self.twilio_sid and self.twilio_token and self.twilio_whatsapp_from and appointment.phone):
            print('WhatsApp not configured or phone missing')
            return
        client = Client(self.twilio_sid, self.twilio_token)
        to = f'whatsapp:{appointment.phone}'
        body = f'Hello {appointment.patient_name}. Appointment booked at {appointment.datetime}.'
        try:
            client.messages.create(body=body, from_=self.twilio_whatsapp_from, to=to)
        except Exception as e:
            print('WhatsApp send failed:', e)
