from flask import Flask, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import pytz
import os

app = Flask(__name__)

# Load service account credentials
SERVICE_ACCOUNT_FILE = 'service_account.json'  # Upload this to your Render instance
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)

calendar_service = build('calendar', 'v3', credentials=credentials)

@app.route('/calendar/today', methods=['GET'])
def get_today_events():
    tz = pytz.timezone('UTC')
    now = datetime.now(tz)
    start_of_day = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=tz)
    end_of_day = start_of_day + timedelta(days=1)

    events_result = calendar_service.events().list(
        calendarId='primary',
        timeMin=start_of_day.isoformat(),
        timeMax=end_of_day.isoformat(),
        singleEvents=True,
        orderBy='startTime'
    ).execute()
    events = events_result.get('items', [])

    output = []
    for event in events:
        output.append({
            'summary': event.get('summary'),
            'start': event['start'].get('dateTime', event['start'].get('date')),
            'end': event['end'].get('dateTime', event['end'].get('date'))
        })

    return jsonify({'events': output})
