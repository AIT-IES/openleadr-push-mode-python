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

from lxml.etree import XMLSyntaxError
from signxml.exceptions import InvalidSignature

from openleadr import utils, OpenADRServer
from openleadr.enums import MEASUREMENTS, SI_SCALE_CODE
from openleadr.messaging import create_message, parse_message, validate_xml_schema
from openleadr.objects import ReportRequest, ReportSpecifier

from openleadr_push_mode.service import RegistrationServicePushMode, ReportServicePushMode

import logging

logger = logging.getLogger('openleadr')


class OpenADRServerPushMode(OpenADRServer):
    '''
    Main server class for PUSH mode.
    Most methods are re-used from OpenLEADR's class OpenADRServer.
    '''

    def __init__(self, vtn_id, auto_register_report=True,
                 cert=None, key=None, passphrase=None,
                 http_cert=None, http_key=None, http_key_passphrase=None,
                 http_ca_file=None, **args):
        '''
        Create a new OpenADR VTN (server) in PUSH mode.
        Parameters are the same as for OpenLEADR's class OpenADRServer.

        :param str vtn_id: An identifier string for this VTN. This is how you identify yourself
            to the VENs that talk to you.
        :param bool auto_register_report: If true, automatically register to all reports
            registered by the VEN.
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
        self.services['report_service'] = ReportServicePushMode(vtn_id, auto_register_report)

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

    async def push_report_request(self, ven_id, report_requests):
        '''
        Send report requests to VEN. This request can be performed only after the VEN has
        registered its available reports.

        :param ven_id: The ID of the VEN ID to which this request will be delivered.
        :type ven_id: str
        :param report_requests: List of report requests.
        :type report_requests: list

        :return: added report request IDs on success, otherwise None
        :rtype: list, None
        '''
        if ven_id not in self.registered_reports:
            return None

        if ven_id not in self.services['report_service'].created_reports:
            self.services['report_service'].created_reports[ven_id] = []

        previously_created_reports = self.services['report_service'].created_reports[ven_id].copy()

        # Generate request.
        request_id = utils.generate_id()
        payload = {'request_id': request_id,
                   'report_requests': report_requests,
                   'ven_id': ven_id}
        request = self._create_message('oadrCreateReport', **payload)

        logger.info(f'Request new reports: {payload}')

        # Now push the request to the VEN.
        if ven_id in self.services['registration_service'].ven_addresses:
            response_type, response_payload = await self._send_report_request(ven_id, request)
            await self.services['report_service'].created_report(response_payload)

            # Return list of newly created report request IDs.
            updated_created_reports = self.services['report_service'].created_reports[ven_id]
            report_request_ids = [r for r in updated_created_reports if r not in previously_created_reports]

            logger.info(f'Created reports: {report_request_ids}')

            return report_request_ids
        else:
            raise ValueError(f'Unknown VEN ID: {ven_id}')

    async def push_cancel_report(self, ven_id, cancel_report_id, report_to_follow=False):
        '''
        Cancel reports from VEN.

        :param ven_id: The ID of the VEN ID to which this request will be delivered.
        :type ven_id: str
        :param cancel_report_id: Report request ID to be cancelled.
        :type cancel_report_id: string
        :param report_to_follow: If true, the VEN is expected to send one final additional report.
        :type report_to_follow: bool

        :return: List of all reports that are scheduled for future delivery.
        :rtype: list
        '''
        if ven_id not in self.registered_reports:
            return None

        if ven_id not in self.services['report_service'].created_reports:
            self.services['report_service'].created_reports[ven_id] = []

        # Generate request.
        request_id = utils.generate_id()
        payload = {'request_id': request_id,
                   'report_request_id': cancel_report_id,
                   'report_to_follow': report_to_follow,
                   'ven_id': ven_id}
        request = self._create_message('oadrCancelReport', **payload)

        logger.info(f'Cancel report: {payload}')

        # Now push the request to the VEN.
        if ven_id in self.services['registration_service'].ven_addresses:
            response_type, response_payload = await self._send_report_request(ven_id, request)
            await self.services['report_service'].cancel_report(response_payload)

            return response_payload.get('pending_reports', [])
        else:
            raise ValueError(f'Unknown VEN ID: {ven_id}')

    async def push_event(self, ven_id, priority=None, measurement_name=None, scale=None, **args):
        '''
        Convenience method to push an event with a single signal.
        Parameters are the same as for method add_event of OpenLEADR's class OpenADRServer.

        :param str ven_id: The ven_id to whom this event must be delivered.
        :param int priority: The priority of this event relative to other events.
        :param str measurement_name: The OpenADR name of the measurement type; one of openleadr.enums.MEASUREMENTS.
        :param str scale: The OpenADR scale of the measurement type; one of openleadr.enums.SI_SCALE_CODE.
        :param str signal_name: The OpenADR name of the signal; one of openleadr.objects.SIGNAL_NAME.
        :param str signal_type: The OpenADR type of the signal; one of openleadr.objects.SIGNAL_TYPE.
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
        try:
            event_id = self.add_event(ven_id=ven_id, **args)
        except Exception as e: 
            logger.error(e)
            return
        event, callback = self.event_callbacks[event_id]

        if (measurement_name is not None):
            if measurement_name not in MEASUREMENTS.members:
                raise ValueError(f"""The measurement_name must be one of '{"', '".join(MEASUREMENTS.members)}'""")
            for signal in event.event_signals:
                signal.measurement = MEASUREMENTS[measurement_name]

        if (scale is not None):
            if scale not in SI_SCALE_CODE.members:
                raise ValueError(f"""The scale must be one of '{"', '".join(SI_SCALE_CODE.members)}'""")
            for signal in event.event_signals:
                signal.measurement.scale = SI_SCALE_CODE[scale]

        if (priority is not None):
            if (type(priority) is not int or priority < 0):
                raise ValueError('The priority must be a non-negative integer')
            event.event_descriptor.priority = priority

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
        logger.info(f'\r{self.vtn_id} stopped.')

    @property
    def report_requests(self):
        return self.services['report_service'].requested_reports.copy()

    @property
    def created_reports(self):
        return self.services['report_service'].created_reports.copy()

    ###########################################################################
    #                                                                         #
    #                  PRE-REGISTRATION (FOR TESTING ONLY)                    #
    #                                                                         #
    ###########################################################################

    async def pre_register_ven(self, ven_name, transport_address,
                               report_only=False, xml_signature=False):
        '''
        Pre-registration of a VEN allows the VEN to skip the party registration
        process. Only intended for testing purposes!

        :param ven_name: name of the VEN
        :type ven_name: str
        :param transport_address: URL of the VEN
        :type transport_address: str
        :param report_only:  indicate the VEN is a Report Only instance of the B profile. (default: False)
        :type report_only: bool
        :param xml_signature: XML signature (default: None)
        :type xml_signature: str or None
        :return: ven_id and registration_id
        :rtype: tuple of str
        '''
        transport_name = 'simpleHttp'
        profile_name = '2.0b'
        http_pull_model = False

        payload = {'ven_name': ven_name,
                   'http_pull_model': http_pull_model,
                   'xml_signature': xml_signature,
                   'report_only': report_only,
                   'profile_name': profile_name,
                   'transport_name': transport_name,
                   'transport_address': transport_address}

        registration_service = self.services['registration_service']
        _, result = await registration_service.create_party_registration(payload)

        ven_id = result['ven_id']
        registration_id = result['registration_id']

        logger.info(f'Pre-registered {ven_name} with ID = {ven_id} under registration ID = {registration_id}.')

        return ven_id, registration_id

    async def pre_register_report(self, ven_id, report_request_id, report_specifier_id, report_id,
                                  resource_id, measurement, unit, scale, sampling_interval):
        '''
        Pre-registration of reports allows to skip the report registration and
        creation process. Only intended for testing purposes!

        :param ven_id: VEN ID
        :type ven_id: str
        :param ven_id: report ID
        :type ven_id: str
        '''
        # Add dummy request to report service.
        report_specifier = ReportSpecifier(report_specifier_id=report_specifier_id,
                                           granularity=None,
                                           specifier_payloads=[])
        report_request = ReportRequest(report_request_id=report_request_id,
                                       report_specifier=report_specifier)

        if ven_id in self.services['report_service'].requested_reports:
            self.services['report_service'].requested_reports[ven_id].append(report_request)
        else:
            self.services['report_service'].requested_reports[ven_id] = [report_request]

        # Add report to service.
        payload = {'pending_reports': [{'report_request_id': report_request_id}],
                   'ven_id': ven_id}
        await self.services['report_service'].created_report(payload)

        # Call on_register_report handler.
        register = self.services['report_service'].on_register_report
        result = await register(ven_id=ven_id, resource_id=resource_id, measurement=measurement,
                                unit=unit, scale=scale, min_sampling_interval=sampling_interval,
                                max_sampling_interval=sampling_interval)
        if result:
            if not isinstance(result, tuple):
                logger.error('Your on_register_report handler must return a tuple or None; '
                             f'it returned "{result}" ({result.__class__.__name__}).')
            # Add callback to report service.
            self.services['report_service'].report_callbacks[(report_request_id, report_id)] = result[0]

        logger.info(f'Pre-registered report with specifier ID={report_specifier_id} from {ven_id}')

    ###########################################################################
    #                                                                         #
    #                                LOW LEVEL                                #
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

    async def _send_report_request(self, ven_id, request):
        address = self.services['registration_service'].ven_addresses[ven_id]
        url = f'{address}/EiReport'
        try:
            async with self.client_session_post.post(url, data=request) as req:
                content = await req.read()
                if req.status != HTTPStatus.OK:
                    logger.warning(f"Non-OK status {req.status} when performing a request to {url} "
                                   f"with data {request}: {req.status} {content.decode('utf-8')}")
                    return None, {}
        except aiohttp.client_exceptions.ClientConnectorError as err:
            # Could not connect to server
            logger.error(f"Could not connect to server with URL {self.vtn_url}:")
            logger.error(f"{err.__class__.__name__}: {str(err)}")
            return None, {}
        except Exception as err:
            logger.error(f"Request error {err.__class__.__name__}:{err}")
            return None, {}

        if len(content) == 0:
            return None

        try:
            validate_xml_schema(content)
            message_type, message_payload = parse_message(content)
        except XMLSyntaxError as err:
            logger.warning(f"Incoming message did not pass XML schema validation: {err}")
            return None, {}
        except InvalidSignature:
            logger.warning("Incoming message had invalid signature, ignoring.")
            return None, {}
        except Exception as err:
            logger.error(f"The incoming message could not be parsed or validated: {err}")
            return None, {}
        if 'response' in message_payload and 'response_code' in message_payload['response']:
            if message_payload['response']['response_code'] != 200:
                logger.warning("We got a non-OK OpenADR response from the server: "
                               f"{message_payload['response']['response_code']}: "
                               f"{message_payload['response']['response_description']}")
        return message_type, message_payload
