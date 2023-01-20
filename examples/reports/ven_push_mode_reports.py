import asyncio
from datetime import timedelta
from openleadr_push_mode import OpenADRClientPushMode
from openleadr import enable_default_logging
import logging

# enable_default_logging(level=logging.DEBUG)
enable_default_logging(level=logging.INFO)

async def collect_report_value():
    # This callback is called when you need to collect a value for your Report
    return 1.23

async def handle_event(event):
    # This callback receives an Event dict.
    # You should include code here that sends control signals to your resources.
    print('Received event:', event)
    return 'optIn'

# Create the client object
simple_client = OpenADRClientPushMode(
    ven_name='ven123',
    vtn_url='http://localhost:8080/OpenADR2/Simple/2.0b',
    )

# Add the report capability to the client
simple_client.add_report(callback=collect_report_value,
                  resource_id='device001',
                  measurement='voltage',
                  sampling_rate=timedelta(seconds=2))
simple_client.add_report(callback=collect_report_value,
                  resource_id='device002',
                  measurement='voltage',
                  sampling_rate=timedelta(seconds=2))

# Add event handling capability to the client
simple_client.add_handler('on_event', handle_event)

# Run the client in the Python AsyncIO Event Loop
loop = asyncio.get_event_loop()
loop.create_task(simple_client.run())
loop.run_forever()
