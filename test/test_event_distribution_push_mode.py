from openleadr_push_mode import OpenADRClientPushMode, OpenADRServerPushMode
from openleadr import enable_default_logging
import pytest
import asyncio
import datetime
from functools import partial

enable_default_logging()

def on_create_party_registration(registration_info):
    return 'ven123', 'reg123'

async def on_event(event):
    return 'optIn'

async def event_callback(ven_id, event_id, opt_type, future):
    if future.done() is False:
        future.set_result(opt_type)

@pytest.mark.asyncio
async def test_internal_message_queue():
    loop = asyncio.get_event_loop()
    client = OpenADRClientPushMode(ven_name='myven',
                                   vtn_url='http://localhost:8080/OpenADR2/Simple/2.0b')
    client.add_handler('on_event', on_event)
    server = OpenADRServerPushMode(vtn_id='myvtn')
    server.add_handler('on_create_party_registration', on_create_party_registration)
    event_callback_future = loop.create_future()

    await server.run()
    await client.run()

    await server.push_event(ven_id='ven123',
                            signal_name='simple',
                            signal_type='level',
                            intervals=[{'dtstart': datetime.datetime.now(datetime.timezone.utc),
                                        'duration': datetime.timedelta(minutes=3),
                                        'signal_payload': 1}],
                            callback=partial(event_callback, future=event_callback_future))

    status = await event_callback_future
    assert status == 'optIn'

    await client.stop()
    await server.stop()
