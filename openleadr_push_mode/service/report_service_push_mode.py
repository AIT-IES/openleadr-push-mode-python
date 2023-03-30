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
from openleadr import utils

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
        self.auto_register = auto_register

    @handler('oadrRegisterReport')
    async def register_report(self, payload):
        response_type, response_payload = await super().register_report(payload)
        if False is self.auto_register:
            response_payload['report_requests'] = []
        return response_type, response_payload

    async def cancel_report(self, payload):
        ven_id = payload['ven_id']

        self.created_reports[ven_id].clear()
        for pending_report in payload.get('pending_reports', []):
            self.created_reports[ven_id].append(pending_report['report_request_id'])

    @handler('oadrUpdateReport')
    async def update_report(self, payload):

        # Check if a callback was registered for this report.
        for report in payload['reports']:
            report_request_id = report['report_request_id']
            for r_id, values in utils.group_by(report['intervals'], 'report_payload.r_id').items():
                if (report_request_id, r_id) not in self.report_callbacks:
                    for ri in values:
                        await self.on_unknown_report(report_request_id, r_id, ri['dtstart'], 
                                                     ri['report_payload']['value'])

        return await super().update_report(payload)
    
    async def on_unknown_report(self, report_request_id, r_id, dtstart, report_payload):
        logger.warning('Received an un-registered report ' + 
                       f'with request ID={report_request_id} and report ID={r_id}: ' +
                       f'time="{dtstart}" - value="{report_payload}"')
