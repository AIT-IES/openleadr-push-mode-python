import asyncio
from datetime import timedelta
from openleadr_push_mode import OpenADRClientPushMode
from openleadr import enable_default_logging
from openleadr.enums import SI_SCALE_CODE
import logging
import random

random.seed(0)

# enable_default_logging(level=logging.DEBUG)
enable_default_logging(level=logging.INFO)

TEST_VTN_ID = 'VTN-TEST'

TEST_VTN_URL = 'http://localhost:8080/OpenADR2/Simple/2.0b'

TEST_VEN_NAME = 'VEN-TEST'

VEN_MEASUREMENT_TYPE = 'REAL_POWER'
VEN_MEASUREMENT_SCALE = SI_SCALE_CODE['k']
VEN_MEASUREMENT_RATE = timedelta(seconds=2)

BASELINE_HOUSE_001 = 40.
BASELINE_HOUSE_002 = 50.

LOAD_DISPATCH_DELTA = 0.

async def collect_report_house_001():
    return BASELINE_HOUSE_001 - LOAD_DISPATCH_DELTA + round(random.uniform(-0.1,0.2), 2)

async def collect_report_house_002():
    return BASELINE_HOUSE_002 - LOAD_DISPATCH_DELTA + round(random.uniform(-0.2,0.1), 2)

async def start_ven(c):
    '''
    Start the VEN, including pre-registration of reports.
    '''
    await c.run(auto_register=False, auto_register_reports=False)

    await c.pre_register_report(report_request_id='REPORT_REQUEST', 
        report_specifier_id='TEST_REPORT', 
        report_ids=['HOUSE_001_REPORT', 'HOUSE_002_REPORT'],
        granularity=timedelta(seconds=2))

# Create the client object
simple_client = OpenADRClientPushMode(
    ven_name=TEST_VEN_NAME,
    vtn_url=TEST_VTN_URL,
    )

# Pre-register client
simple_client.pre_register_ven(ven_id=TEST_VEN_NAME, 
    vtn_id=TEST_VTN_ID
    )

# Add the report capability to the client
simple_client.add_report(callback=collect_report_house_001,
    report_specifier_id='TEST_REPORT',
    resource_id='HOUSE_001',
    r_id='HOUSE_001_REPORT',
    measurement=VEN_MEASUREMENT_TYPE,
    scale=VEN_MEASUREMENT_SCALE,
    sampling_rate=VEN_MEASUREMENT_RATE,
    report_duration=timedelta(weeks=1))

simple_client.add_report(callback=collect_report_house_002,
    report_specifier_id='TEST_REPORT',
    resource_id='HOUSE_002',
    r_id='HOUSE_002_REPORT',
    measurement=VEN_MEASUREMENT_TYPE,
    scale=VEN_MEASUREMENT_SCALE,
    sampling_rate=VEN_MEASUREMENT_RATE,
    report_duration=timedelta(weeks=1))


# Get the asyncio event loop
loop = asyncio.get_event_loop()

# Create task for VEN start-up and pre-registration
loop.create_task(start_ven(simple_client))

# Run the client in the asyncio event loop
try:
    loop.run_forever()
except KeyboardInterrupt:
    loop.run_until_complete(simple_client.stop())
