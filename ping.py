import time
import requests

METER_ID = 101

DJANGO_SERVER_URL = 'http://127.0.0.1:8000'
DJANGO_STATUS_API_URL = DJANGO_SERVER_URL + '/ping/'

time_now = time.strftime("%Y-%m-%d %H:%M:%S")
payload = {
    'timestamp': time_now,
    'meter_id': METER_ID
}

post_request = requests.post(DJANGO_STATUS_API_URL, data = payload)