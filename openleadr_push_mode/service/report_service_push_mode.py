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

from openleadr.service import service, handler, ReportService
# from asyncio import iscoroutine

import logging

logger = logging.getLogger('openleadr')


@service('EiReport')
class ReportServicePushMode(ReportService):
    '''
    VTN report service for PUSH mode.
    Most methods are re-used from OpenLEADR's class RegistrationService.
    '''

    def __init__(self, vtn_id, auto_register=True):
        super().__init__(vtn_id)
        self.auto_register=auto_register

    @handler('oadrRegisterReport')
    async def register_report(self, payload):
        response_type, response_payload = await super().register_report(payload)
        if False is self.auto_register:
            response_payload['report_requests'] = []
        return response_type, response_payload
