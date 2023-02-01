from pathlib import Path
import asyncio
from datetime import datetime, timezone, timedelta
from openleadr_push_mode import OpenADRServerPushMode
from openleadr import enable_default_logging
from openleadr.utils import certificate_fingerprint
from functools import partial
import logging

# enable_default_logging(level=logging.DEBUG)
enable_default_logging(level=logging.INFO)

CA_CERT  = Path(__file__).parent / 'certs' / 'dummy_ca.crt'
VTN_CERT = Path(__file__).parent / 'certs' / 'dummy_vtn.crt'
VTN_KEY  = Path(__file__).parent / 'certs' / 'dummy_vtn.key'
VEN_CERT = Path(__file__).parent / 'certs' / 'dummy_ven.crt'
VEN_KEY  = Path(__file__).parent / 'certs' / 'dummy_ven.key'

def ven_lookup(ven_id):
    if ven_id == 'ven_id_123':
        with open(VEN_CERT) as file:
            ven_fingerprint = certificate_fingerprint(file.read())

        return dict(ven_name='ven123',
            ven_id='ven_id_123',
            registration_id='reg_id_123',
            fingerprint=ven_fingerprint)
    else:
        return dict()


async def on_create_party_registration(registration_info):
    '''
    Inspect the registration info and return a ven_id and registration_id.
    '''
    if registration_info['ven_name'] == 'ven123':
        ven_id = 'ven_id_123'
        registration_id = 'reg_id_123'
        ven_info = ven_lookup(ven_id)

        if 'fingerprint' in registration_info.keys() and registration_info['fingerprint'] != ven_info['fingerprint']:
            raise errors.FingerprintMismatch('The fingerprint of your TLS connection does not match the expected fingerprint. Your VEN is not allowed to register.')
        return ven_id, registration_id
    else:
        return False

async def on_register_report(ven_id, resource_id, measurement, unit, scale,
                             min_sampling_interval, max_sampling_interval):
    '''
    Inspect a report offering from the VEN and return a callback and sampling interval for receiving the reports.
    '''
    callback = partial(on_update_report, ven_id=ven_id, resource_id=resource_id, measurement=measurement)
    sampling_interval = min_sampling_interval
    return callback, sampling_interval

async def on_update_report(data, ven_id, resource_id, measurement):
    '''
    Callback that receives report data from the VEN and handles it.
    '''
    for time, value in data:
        print(f'Ven {ven_id} reported {measurement} = {value} at time {time} for resource {resource_id}')

async def event_response_callback(ven_id, event_id, opt_type):
    '''
    Callback that receives the response from a VEN to an Event.
    '''
    print(f'VEN {ven_id} responded to Event {event_id} with: {opt_type}')


async def push(s, delay):
    '''
    Push an event to a VEN with a given delay.
    '''
    await asyncio.sleep(delay)
    id = await s.push_event(
        ven_id='ven_id_123',
        signal_name='simple',
        signal_type='level',
        intervals=[{'dtstart': datetime.now(tz=timezone.utc) + timedelta(minutes=5),
                    'duration': timedelta(minutes=10),
                    'signal_payload': 1}],
        callback=event_response_callback
        )

    if id != None:
        print(f'Successfully pushed event with ID={id}')
    else:
        print('Failed to push event')

# Create the server object
secure_server = OpenADRServerPushMode(
    vtn_id='myvtn',
    http_cert=VTN_CERT,
    http_key=VTN_KEY,
    http_ca_file=CA_CERT,
    cert=VTN_CERT,
    key=VTN_KEY,
    ven_lookup=ven_lookup
    )

# Add the handler for client (VEN) registrations
secure_server.add_handler('on_create_party_registration', on_create_party_registration)

# Add the handler for report registrations from the VEN
secure_server.add_handler('on_register_report', on_register_report)

# Run the server on the asyncio event loop
loop = asyncio.get_event_loop()
loop.create_task(secure_server.run())

# Push an event later.
loop.create_task(push(secure_server, 5))

try:
    loop.run_forever()
except KeyboardInterrupt:
    loop.run_until_complete(secure_server.stop())
