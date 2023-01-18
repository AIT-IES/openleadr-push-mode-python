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

from openleadr.service import service, handler, RegistrationService
from asyncio import iscoroutine

import logging

logger = logging.getLogger('openleadr')


@service('EiRegisterParty')
class RegistrationServicePushMode(RegistrationService):
    '''
    VTN registration service for PUSH mode.
    Most methods are re-used from OpenLEADR's class RegistrationService.
    '''

    def __init__(self, vtn_id):
        super().__init__(vtn_id, None)
        self.ven_addresses = {}

    @handler('oadrCreatePartyRegistration')
    async def create_party_registration(self, payload):
        '''
        Handle the registration of a VEN party.
        '''
        if 'transport_address' not in payload or str(payload['transport_address']) == 'None':
            logger.info('Client registration request is missing a PUSH address.'
                        'Will REJECT the client for now.')
            return 'oadrCreatedPartyRegistration', {}

        result = self.on_create_party_registration(payload)
        if iscoroutine(result):
            result = await result

        if result is not False and result is not None:
            if len(result) != 2:
                logger.error('Your on_create_party_registration handler should return either '
                             '\'False\' (if the client is rejected) or a (ven_id, registration_id) '
                             'tuple. Will REJECT the client for now.')
                response_payload = {}
            else:
                ven_id, registration_id = result

                self.ven_addresses[ven_id] = payload['transport_address']

                transports = [{'transport_name': payload['transport_name']}]
                response_payload = {'ven_id': result[0],
                                    'registration_id': result[1],
                                    'profiles': [{'profile_name': payload['profile_name'],
                                                  'transports': transports}]}
        else:
            transports = [{'transport_name': payload['transport_name']}]
            response_payload = {'profiles': [{'profile_name': payload['profile_name'],
                                              'transports': transports}]}
        return 'oadrCreatedPartyRegistration', response_payload

    def on_create_party_registration(self, payload):
        '''
        Placeholder for the on_create_party_registration handler
        '''
        logger.warning('You should implement and register your own on_create_party_registration '
                       'handler if you want VENs to be able to connect to you. This handler will '
                       'receive a registration request and should return either \'False\' (if the '
                       'registration is denied) or a (ven_id, registration_id) tuple if the '
                       'registration is accepted.')
        return False
