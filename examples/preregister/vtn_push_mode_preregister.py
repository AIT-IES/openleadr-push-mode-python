import asyncio
from functools import partial
from datetime import datetime, timezone, timedelta
from openleadr_push_mode import OpenADRServerPushMode
from openleadr.enums import SI_SCALE_CODE
from openleadr import enable_default_logging
import logging

# enable_default_logging(level=logging.DEBUG)
enable_default_logging(level=logging.INFO)

LOGGER = logging.getLogger('openleadr')

TEST_VTN_ID = 'VTN-TEST'

TEST_VEN_NAME = 'VEN-TEST'

TEST_VEN_URL = 'http://localhost:8081/OpenADR2/Simple/2.0b'

VEN_REGISTRATION_LIST = {
    TEST_VEN_NAME: 'REGISTRATION-ID-TEST'
}

VEN_MEASUREMENT_TYPE = 'REAL_POWER'
VEN_MEASUREMENT_UNIT = 'W'
VEN_MEASUREMENT_SCALE = SI_SCALE_CODE['k']
VEN_MEASUREMENT_RATE = timedelta(seconds=2)

async def on_party_preregistration(registration_info):
    '''
    Inspect the registration info and return a ven_id and registration_id.
    '''
    ven_id = registration_info['ven_name']
    if ven_id in VEN_REGISTRATION_LIST:
        registration_id = VEN_REGISTRATION_LIST[ven_id]        
        return ven_id, registration_id
    else:
        LOGGER.error(f'Pre-registration of VEN with ID={ven_id} failed.')
        return False

async def on_preregister_report(ven_id, resource_id, measurement, unit, scale,
                             min_sampling_interval, max_sampling_interval):
    '''
    Inspect a report offering and return a callback and sampling interval for receiving the reports.
    '''
    callback = partial(on_update_report, ven_id=ven_id, resource_id=resource_id, measurement=measurement)
    sampling_interval = min_sampling_interval
    return callback, sampling_interval

async def on_update_report(data, ven_id, resource_id, measurement):
    '''
    Callback that receives report data from the VEN and handles it.
    '''
    for time, value in data:
        LOGGER.info(f'VEN {ven_id} reported {measurement} = {value} at time {time} for resource {resource_id}')

async def preregister_ven(s):
    '''
    Start the VTN, including pre-registration of VEN.
    '''
    await s.run()
    id, _ = await s.pre_register_ven(ven_name=TEST_VEN_NAME,
        transport_address=TEST_VEN_URL)

    report_registration_data = dict(ven_id=id, 
        report_request_id='REPORT_REQUEST', report_specifier_id='TEST_REPORT',
        measurement=VEN_MEASUREMENT_TYPE, unit=VEN_MEASUREMENT_UNIT,
        scale=VEN_MEASUREMENT_SCALE, sampling_interval=VEN_MEASUREMENT_RATE)
    await s.pre_register_report( **report_registration_data,
        report_id='HOUSE_001_REPORT', resource_id='HOUSE_001')
    await s.pre_register_report( **report_registration_data,
        report_id='HOUSE_002_REPORT', resource_id='HOUSE_002')

# Create the server object
simple_server = OpenADRServerPushMode(vtn_id=TEST_VTN_ID, auto_register_report=False)

# Add the handler for client (VEN) pre-registration
simple_server.add_handler('on_create_party_registration', on_party_preregistration)

# Add the handler for report pre-registration
simple_server.add_handler('on_register_report', on_preregister_report)

# Get the asyncio event loop
loop = asyncio.get_event_loop()

# Create task for VEN pre-registration
loop.create_task(preregister_ven(simple_server))

# Run the server in the asyncio event loop
try:
    loop.run_forever()
except KeyboardInterrupt:
    loop.run_until_complete(simple_server.stop())
