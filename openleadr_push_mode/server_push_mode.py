# SPDX-License-Identifier: Apache-2.0

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from functools import partial

import asyncio

import aiohttp
from http import HTTPStatus
import ssl

from openleadr import utils, OpenADRServer
from openleadr.messaging import create_message

from openleadr_push_mode.service import RegistrationServicePushMode

import logging

logger = logging.getLogger('openleadr')


class OpenADRServerPushMode(OpenADRServer):
    '''
    Main server class for PUSH mode.
    Most methods are re-used from OpenLEADR's class OpenADRServer.
    '''

    def __init__(self, vtn_id, cert=None, key=None, passphrase=None,
                 http_cert=None, http_key=None, http_key_passphrase=None,
                 http_ca_file=None, **args):
        '''
        Create a new OpenADR VTN (server) in PUSH mode.
        Parameters are the same as for OpenLEADR's class OpenADRServer.

        :param str vtn_id: An identifier string for this VTN. This is how you identify yourself
            to the VENs that talk to you.
        :param str cert: Path to the PEM-formatted certificate file that is used to sign outgoing
            messages
        :param str key: Path to the PEM-formatted private key file that is used to sign outgoing
            messages
        :param str passphrase: The passphrase used to decrypt the private key file
        :param callable fingerprint_lookup: A callable that receives a ven_id and should return the
            registered fingerprint for that VEN. You should receive these fingerprints outside of
            OpenADR and configure them manually.
        :param bool show_fingerprint: Whether to print the fingerprint to your stdout on startup.
            Defaults to True.
        :param int http_port: The port that the web server is exposed on (default: 8080)
        :param str http_host: The host or IP address to bind the server to (default: 127.0.0.1).
        :param str http_cert: The path to the PEM certificate for securing HTTP traffic.
        :param str http_key: The path to the PEM private key for securing HTTP traffic.
        :param str http_ca_file: The path to the CA-file that client certificates are checked against.
        :param str http_key_passphrase: The passphrase for the HTTP private key.
        :param ven_lookup: A callback that takes a ven_id and returns a dict containing the
            ven_id, ven_name, fingerprint and registration_id.
        '''
        super().__init__(vtn_id=vtn_id, cert=cert, key=key, passphrase=passphrase,
                         http_cert=http_cert, http_key=http_key, http_key_passphrase=http_key_passphrase,
                         http_ca_file=http_ca_file, **args)

        self.vtn_id = vtn_id

        # Set up the message queues.
        self.app = aiohttp.web.Application()
        self.services['registration_service'] = RegistrationServicePushMode(vtn_id)

        # Set up the HTTP handlers for the services
        self.app.add_routes([aiohttp.web.post(f'{self.http_path_prefix}/{s.__service_name__}', s.handler)
                             for s in self.services.values()])

        # Add a reference to the openadr VTN to the aiohttp 'app'
        self.app['server'] = self

        headers = {'content-type': 'application/xml'}
        if http_cert and http_key and http_ca_file:
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ssl_context.load_verify_locations(http_ca_file)
            ssl_context.load_cert_chain(http_cert, http_key, http_key_passphrase)
            # ssl_context.check_hostname = check_hostname
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            self.client_session_post = aiohttp.ClientSession(connector=connector, headers=headers)
        else:
            self.client_session_post = aiohttp.ClientSession(headers=headers)

        if cert and key:
            with open(cert, 'rb') as file:
                cert = file.read()
            with open(key, 'rb') as file:
                key = file.read()

        self._create_message = partial(create_message, cert=cert, key=key, passphrase=passphrase)

    async def push_event(self, ven_id, **args):
        '''
        Convenience method to push an event with a single signal.
        Parameters are the same as for method add_event of OpenLEADR's class OpenADRServer.

        :param str ven_id: The ven_id to whom this event must be delivered.
        :param str signal_name: The OpenADR name of the signal; one of openleadr.objects.SIGNAL_NAME
        :param str signal_type: The OpenADR type of the signal; one of openleadr.objects.SIGNAL_TYPE
        :param str intervals: A list of intervals with a dtstart, duration and payload member.
        :param str callback: A callback function for when your event has been accepted (optIn) or refused (optOut).
        :param list targets: A list of Targets that this Event applies to.
        :param target: A single target for this event.
        :param dict targets_by_type: A dict of targets, grouped by type.
        :param str market_context: A URI for the DR program that this event belongs to.
        :param timedelta notification_period: The Notification period for the Event's Active Period.
        :param timedelta ramp_up_period: The Ramp Up period for the Event's Active Period.
        :param timedelta recovery_period: The Recovery period for the Event's Active Period.

        If you don't provide a target using any of the three arguments, the target will be set to the given ven_id.
        '''

        event_id = self.add_event(ven_id=ven_id, **args)
        event, callback = self.event_callbacks[event_id]

        # Now push the event to the VEN.
        if ven_id in self.services['registration_service'].ven_addresses:
            address = self.services['registration_service'].ven_addresses[ven_id]
            status = await self._distribute_events(ven_id=ven_id, events=utils.order_events(event), address=address)
            if status != HTTPStatus.OK:
                logger.warning(f'Cannot push event (ID={event_id}), VEN client reponse status: {status}')
                self._remove_event(ven_id, event_id)
                return
        else:
            logger.warning(f'Cannot push event (ID={event_id}), VEN ID unknown: {ven_id}')
            self._remove_event(ven_id, event_id)
            return

        return event_id

    async def stop(self):
        '''
        Cleanly stops the server. Run this coroutine before closing your event loop.
        '''
        await super().stop()
        await self.client_session_post.close()
        await asyncio.sleep(0)

    ###########################################################################
    #                                                                         #
    #                                  LOW LEVEL                              #
    #                                                                         #
    ###########################################################################

    def _remove_event(self, ven_id, event_id):
        '''
        Remove a scheduled event from the event service's queue.
        '''
        logger.warning(f'Remove event with ID: {event_id}')
        utils.pop_by(self.events[ven_id], 'event_descriptor.event_id', event_id)
        self.event_callbacks.pop(event_id)

    async def _distribute_events(self, ven_id, events, address):
        '''
        Push events to VEN in a message of type oadrDistributeEvent.
        '''
        url = f'{address}/EiEvent'
        message = self._create_message('oadrDistributeEvent',
                                       ven_id=ven_id, vtn_id=self.vtn_id, events=events)
        try:
            async with self.client_session_post.post(url, data=message) as req:
                content = await req.read()
                if req.status != HTTPStatus.OK:
                    logger.warning(f'Non-OK status {req.status} when performing a request to {url} '
                                   f'with data {message}: {req.status} {content.decode("utf-8")}')
                if len(content) != 0:
                    logger.warning(f'Non-empty response to oadrDistributeEvent: {content.decode("utf-8")}')
                return req.status
        except aiohttp.client_exceptions.ClientConnectorError as err:
            # Could not connect to server
            logger.error(f'Could not connect to server with URL {address}:')
            logger.error(f'{err.__class__.__name__}: {str(err)}')
            return
        except Exception as err:
            logger.error(f'Request error {err.__class__.__name__}:{err}')
            return
