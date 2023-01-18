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

from datetime import datetime, timedelta
import tzlocal

import asyncio

import aiohttp
from http import HTTPStatus
import ssl

from openleadr import errors, hooks, utils, OpenADRClient
from openleadr.messaging import parse_message, validate_xml_schema, validate_xml_signature

import logging

logger = logging.getLogger('openleadr')


class OpenADRClientPushMode(OpenADRClient):
    '''
    Main client class for PUSH mode.
    Most methods are re-used from OpenLEADR's class OpenADRClient.
    '''

    # Default delay (in seconds) for sending a response of type 'oadrCreatedEvent'
    # after acknowledging a request of type 'oadrDistributeEvent'.
    CREATED_EVENT_RESPONSE_DELAY = 3

    def __init__(self, http_port=8081, http_host='localhost', ca_file=None,
                 http_cert=None, http_key=None, http_key_passphrase=None,
                 http_path_prefix='/OpenADR2/Simple/2.0b', **args):
        '''
        Create a new OpenADR VEN (client) in PUSH mode.
        Most parameters are the same as for OpenLEADR's class OpenADRClient.

        :param str ven_name: The name for this VEN
        :param str vtn_url: The URL of the VTN (Server) to connect to
        :param bool debug: Whether or not to print debugging messages
        :param str cert: The path to a PEM-formatted Certificate file to use for signing messages.
        :param str key: The path to a PEM-formatted Private Key file to use for signing messages.
        :param str passphrase: The passphrase for the Private Key
        :param str vtn_fingerprint: The fingerprint for the VTN's certificate to verify incomnig messages
        :param str show_fingerprint: Whether to print your own fingerprint on startup. Defaults to True.
        :param str ca_file: The path to the PEM-formatted CA file for validating the VTN server's certificate.
        :param str ven_id: The ID for this VEN. If you leave this blank, a VEN_ID will be assigned by the VTN.
        :param bool disable_signature: Whether or not to sign outgoing messages using a public-private key
            pair in PEM format.

        :param int http_port: The port that the web server is exposed on (default: 8081)
        :param str http_host: The host or IP address to bind the server to (default: 127.0.0.1).
        :param str http_cert: The path to the PEM certificate for securing HTTP traffic (default: None).
        :param str http_key: The path to the PEM private key for securing HTTP traffic (default: None).
        :param str http_key_passphrase: The passphrase for the HTTP private key (default: None).
        :param str http_path_prefix: Prefix for service endpoint URIs (default: /OpenADR2/Simple/2.0b).
        '''
        super().__init__(ca_file=ca_file, **args)

        # Configure the web server
        self.http_port = http_port
        self.http_host = http_host
        self.http_path_prefix = http_path_prefix

        # Create SSL context for running the server
        if http_cert and http_key and ca_file:
            self.ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.ssl_context.load_verify_locations(ca_file)
            self.ssl_context.verify_mode = ssl.CERT_REQUIRED
            self.ssl_context.load_cert_chain(http_cert, http_key, http_key_passphrase)
        else:
            self.ssl_context = None

        self.app = aiohttp.web.Application()
        self.app['server'] = self

    async def run(self):
        '''
        Run the client in push mode.
        '''
        # Add handler for receiving events from the server (VEN client event service).
        self.app.add_routes([aiohttp.web.post(f'{self.http_path_prefix}/EiEvent', self._on_push_event)])

        # Add handler for report requests from the server (VEN client report service).
        self.app.add_routes([aiohttp.web.post(f'{self.http_path_prefix}/EiReport', self._on_push_create_report)])

        protocol = 'https' if self.ssl_context else 'http'
        address = f'{protocol}://{self.http_host}:{self.http_port}{self.http_path_prefix}'

        self.app_runner = aiohttp.web.AppRunner(self.app)
        await self.app_runner.setup()
        site = aiohttp.web.TCPSite(self.app_runner,
                                   port=self.http_port,
                                   host=self.http_host,
                                   ssl_context=self.ssl_context)
        await site.start()

        print('')
        print('*' * 80)
        print('Your VEN client is now running in PUSH mode at '.center(80))
        print(f'{protocol}://{self.http_host}:{self.http_port}{self.http_path_prefix}'.center(80))
        print('*' * 80)
        print('')

        _, registration_response_payload = \
            await self.create_party_registration(ven_id=self.ven_id,
                                                 http_pull_model=False,
                                                 transport_address=address)

        if not self.registration_id:
            logger.error('No RegistrationID received from the VTN, aborting.')
            await self.stop()
            return

        if 'vtn_id' in registration_response_payload:
            self.vtn_id = registration_response_payload['vtn_id']
        else:
            logger.warning('No VTN ID received.')
            self.vtn_id = None

        if self.reports:
            await self.register_reports(self.reports)

            loop = asyncio.get_event_loop()
            self.report_queue_task = loop.create_task(self._report_queue_worker())

        self.scheduler.start()

    async def stop(self):
        '''
        Stop the client in a graceful manner.
        '''
        await super().stop()
        await self.app_runner.cleanup()

    ###########################################################################
    #                                                                         #
    #                             REPORTING METHODS                           #
    #                                                                         #
    ###########################################################################

    async def register_reports(self, reports):
        '''
        Tell the VTN about our reports. The VTN might respond with an
        oadrCreateReport message that tells us which reports are to be sent.
        This methods is basically a copy from OpenADRClient, except that
        it will not send a message of type oadrCreatedReport in case no
        reports have been requested.
        '''
        request_id = utils.generate_id()
        payload = {'request_id': request_id,
                   'ven_id': self.ven_id,
                   'reports': reports,
                   'report_request_id': 0}

        for report in payload['reports']:
            utils.setmember(report, 'report_request_id', 0)

        service = 'EiReport'
        message = self._create_message('oadrRegisterReport', **payload)
        response_type, response_payload = await self._perform_request(service, message)

        # Handle the subscriptions that the VTN is interested in.
        if 'report_requests' in response_payload:
            for report_request in response_payload['report_requests']:
                await self.create_report(report_request)

        # Send the oadrCreatedReport message (if reports have been requested).
        if 0 != len(self.report_requests):
            message_type = 'oadrCreatedReport'
            message_payload = {'pending_reports':
                            [{'report_request_id': utils.getmember(report, 'report_request_id')}
                                for report in self.report_requests]}
            message = self._create_message(message_type,
                                        response={'response_code': 200,
                                                    'response_description': 'OK'},
                                        ven_id=self.ven_id,
                                        **message_payload)
            response_type, response_payload = await self._perform_request(service, message)

    ###########################################################################
    #                                                                         #
    #                                  LOW LEVEL                              #
    #                                                                         #
    ###########################################################################

    async def _on_push_event(self, request):
        '''
        Handler for event service.
        '''
        content_type = request.headers.get('content-type', '')
        if not content_type.lower().startswith('application/xml'):
            raise errors.HTTPError(response_code=HTTPStatus.BAD_REQUEST,
                                   response_description=f'The Content-Type header must be application/xml; '
                                                        f'you provided {request.headers.get("content-type", "")}')
        content = await request.read()

        hooks.call('before_parse', content)

        # Validate the message to the XML Schema
        message_tree = validate_xml_schema(content)

        # Parse the message to a type and payload dict
        message_type, message_payload = parse_message(content)

        if 'vtn_id' in message_payload and message_payload['vtn_id'] is not None and message_payload['vtn_id'] != self.vtn_id:
            raise errors.InvalidIdError(f'The supplied vtnID is invalid. It should be "{self.vtn_id}", '
                                        f'you supplied "{message_payload["vtn_id"]}".')

        if self.vtn_fingerprint:
            await self._authenticate_message(request, message_tree, message_payload)

        if message_type != 'oadrDistributeEvent':
            logger.warning(f'Expected message of type \'oadrDistributeEvent\', but got \'{message_type}\'')
            return aiohttp.web.Response(status=HTTPStatus.BAD_REQUEST)

        # This handler returns with HTTP status OK (200). However, the VTN expects as
        # acknowledgement a message of type 'oadrCreatedEvent'. This message will be
        # scheduled with a short delay.
        delay = OpenADRClientPushMode.CREATED_EVENT_RESPONSE_DELAY
        response_date = datetime.now(tz=tzlocal.get_localzone()) + timedelta(seconds=delay)
        self.scheduler.add_job(self._on_event, args=[message_payload], run_date=response_date)

        response = aiohttp.web.Response(status=HTTPStatus.OK)
        hooks.call('before_respond', response.text)
        return response

    async def _on_push_create_report(self, request):
        '''
        Handler for report service.
        '''
        content_type = request.headers.get('content-type', '')
        if not content_type.lower().startswith('application/xml'):
            raise errors.HTTPError(response_code=HTTPStatus.BAD_REQUEST,
                                   response_description=f'The Content-Type header must be application/xml; '
                                                        f'you provided {request.headers.get("content-type", "")}')
        content = await request.read()

        hooks.call('before_parse', content)

        # Validate the message to the XML Schema
        message_tree = validate_xml_schema(content)

        # Parse the message to a type and payload dict
        message_type, message_payload = parse_message(content)

        if 'vtn_id' in message_payload and message_payload['vtn_id'] is not None and message_payload['vtn_id'] != self.vtn_id:
            raise errors.InvalidIdError(f'The supplied vtnID is invalid. It should be "{self.vtn_id}", '
                                        f'you supplied "{message_payload["vtn_id"]}".')

        if self.vtn_fingerprint:
            await self._authenticate_message(request, message_tree, message_payload)

        if message_type != 'oadrCreateReport':
            logger.warning(f'Expected message of type \'oadrCreateReport\', but got \'{message_type}\'')
            return aiohttp.web.Response(status=HTTPStatus.BAD_REQUEST)

        # Handle the subscriptions that the VTN is interested in.
        if 'report_requests' in message_payload:
            for report_request in message_payload['report_requests']:
                await self.create_report(report_request)

        # Send the oadrCreatedReport message
        message_type = 'oadrCreatedReport'
        message_payload = {'pending_reports':
                           [{'report_request_id': utils.getmember(report, 'report_request_id')}
                            for report in self.report_requests]}
        message = self._create_message(message_type,
                                       response={'response_code': 200,
                                                 'response_description': 'OK'},
                                       ven_id=self.ven_id,
                                       **message_payload)
        response = aiohttp.web.Response(text=message,
                                        status=HTTPStatus.OK,
                                        content_type='application/xml')
        return response

    async def _authenticate_message(self, request, message_tree, message_payload):
        if request.secure and 'vtn_id' in message_payload:
            connection_fingerprint = utils.get_cert_fingerprint_from_request(request)
            if connection_fingerprint is None:
                msg = ('Your request must use a server side SSL certificate, of which the '
                       'fingerprint must match the fingerprint that you have given to this VEN.')
                raise errors.NotRegisteredOrAuthorizedError(msg)

            vtn_id = message_payload.get('vtn_id')
            expected_fingerprint = await utils.await_if_required(self.vtn_fingerprint)
            if not expected_fingerprint:
                msg = f'Your VTN ID {vtn_id} is not known to this VEN.'
                raise errors.NotRegisteredOrAuthorizedError(msg)

            if expected_fingerprint is None:
                msg = 'This VEN server does not know what your certificate fingerprint is.'
                raise errors.NotRegisteredOrAuthorizedError(msg)

            if connection_fingerprint != expected_fingerprint:
                msg = (f'The fingerprint of your HTTPS certificate "{connection_fingerprint}" '
                       f'does not match the expected fingerprint "{expected_fingerprint}"')
                raise errors.NotRegisteredOrAuthorizedError(msg)

            message_cert = utils.extract_pem_cert(message_tree)
            message_fingerprint = utils.certificate_fingerprint(message_cert)
            if message_fingerprint != expected_fingerprint:
                msg = (f'The fingerprint of the certificate used to sign the message '
                       f'{message_fingerprint} did not match the fingerprint that this '
                       f'VEN has for you {expected_fingerprint}. Make sure you use the correct '
                       f'certificate to sign your messages.')
                raise errors.NotRegisteredOrAuthorizedError(msg)

            try:
                validate_xml_signature(message_tree)
            except ValueError:
                msg = ('The message signature did not match the message contents. Please make sure '
                       'you are using the correct XMLDSig algorithm and C14n canonicalization.')
                raise errors.NotRegisteredOrAuthorizedError(msg)
