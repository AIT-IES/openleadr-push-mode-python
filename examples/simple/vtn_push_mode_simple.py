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

async def push(s, delay):
    '''
    Push an event to a VEN with a given delay.
    '''
    await asyncio.sleep(delay)
    id = await s.push_event(
        ven_id='ven_id_123',
        priority=1,
        signal_name='LOAD_DISPATCH',
        signal_type='delta',
        measurement_name='REAL_POWER',
        scale='k',
        intervals=[{'dtstart': datetime.now(tz=timezone.utc) + timedelta(minutes=5),
                    'duration': timedelta(minutes=10),
                    'signal_payload': 3.1}],
        market_context='oadr://my_market',
        callback=event_response_callback
        )

    if id != None:
        print(f'Successfully pushed event with ID={id}')
    else:
        print('Failed to push event')

# Create the server object
simple_server = OpenADRServerPushMode(vtn_id='myvtn')

# Add the handler for client (VEN) registrations
simple_server.add_handler('on_create_party_registration', on_create_party_registration)

# Add the handler for report registrations from the VEN
simple_server.add_handler('on_register_report', on_register_report)

# Run the server on the asyncio event loop
loop = asyncio.get_event_loop()
loop.create_task(simple_server.run())

# Push an event later.
loop.create_task(push(simple_server, 5))

loop.run_forever()
