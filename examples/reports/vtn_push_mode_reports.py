import asyncio
from functools import partial
from datetime import datetime, timezone, timedelta
from openleadr_push_mode import OpenADRServerPushMode
from openleadr import enable_default_logging
import logging

# enable_default_logging(level=logging.DEBUG)
enable_default_logging(level=logging.INFO)

async def on_create_party_registration(registration_info):
    '''
    Inspect the registration info and return a ven_id and registration_id.
    '''
    if registration_info['ven_name'] == 'ven123':
        ven_id = 'ven_id_123'
        registration_id = 'reg_id_123'
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

async def push_report_cancelation(s, delay):
    '''
    Push a report request to a VEN with a given delay.
    '''
    await asyncio.sleep(delay)
    created_reports = s.created_reports['ven_id_123']
    report_request_ids = await s.push_cancel_report('ven_id_123', created_reports[0], True)

async def push_report_registration(s, delay):
    '''
    Push a report request to a VEN with a given delay.
    '''
    await asyncio.sleep(delay)
    report_requests = s.report_requests['ven_id_123']
    report_requests[0].report_specifier.specifier_payloads.pop()
    report_request_ids = await s.push_report_request('ven_id_123', report_requests)

# Create the server object
simple_server = OpenADRServerPushMode(vtn_id='myvtn', auto_register_report=True)

# Add the handler for client (VEN) registrations
simple_server.add_handler('on_create_party_registration', on_create_party_registration)

# Add the handler for report registrations from the VEN
simple_server.add_handler('on_register_report', on_register_report)

# Run the server on the asyncio event loop
loop = asyncio.get_event_loop()
loop.create_task(simple_server.run())

# Push a report cancelation later.
loop.create_task(push_report_cancelation(simple_server, 10))

# Push another report registration after the cancelation.
loop.create_task(push_report_registration(simple_server, 15))

try:
    loop.run_forever()
except KeyboardInterrupt:
    loop.run_until_complete(simple_server.stop())
