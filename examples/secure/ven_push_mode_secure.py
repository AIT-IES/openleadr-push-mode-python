from pathlib import Path
import asyncio
from datetime import timedelta
from openleadr_push_mode import OpenADRClientPushMode
from openleadr import enable_default_logging
from openleadr.utils import certificate_fingerprint
import logging

# enable_default_logging(level=logging.DEBUG)
enable_default_logging(level=logging.INFO)

CA_CERT  = Path(__file__).parent / 'certs' / 'dummy_ca.crt'
VTN_CERT = Path(__file__).parent / 'certs' / 'dummy_vtn.crt'
VTN_KEY  = Path(__file__).parent / 'certs' / 'dummy_vtn.key'
VEN_CERT = Path(__file__).parent / 'certs' / 'dummy_ven.crt'
VEN_KEY  = Path(__file__).parent / 'certs' / 'dummy_ven.key'

with open(VTN_CERT) as file:
    vtn_fingerprint = certificate_fingerprint(file.read())

async def collect_report_value():
    # This callback is called when you need to collect a value for your Report
    return 1.23

async def handle_event(event):
    # This callback receives an Event dict.
    # You should include code here that sends control signals to your resources.
    print('Received event:', event)
    return 'optIn'

# Create the client object
secure_client = OpenADRClientPushMode(
    ven_name='ven123',
    vtn_url='https://localhost:8080/OpenADR2/Simple/2.0b',
    http_cert=VEN_CERT,
    http_key=VEN_KEY,
    cert=VEN_CERT,
    key=VEN_KEY,
    ca_file=CA_CERT,
    vtn_fingerprint=vtn_fingerprint
    )

# Add the report capability to the client
secure_client.add_report(callback=collect_report_value,
                  resource_id='device001',
                  measurement='voltage',
                  sampling_rate=timedelta(seconds=10))

# Add event handling capability to the client
secure_client.add_handler('on_event', handle_event)

# Run the client in the Python AsyncIO Event Loop
loop = asyncio.get_event_loop()
loop.create_task(secure_client.run())

try:
    loop.run_forever()
except KeyboardInterrupt:
    loop.run_until_complete(secure_client.stop())
