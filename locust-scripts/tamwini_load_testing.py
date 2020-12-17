import os
import zmq
import logging
import copy
import json

from locust import (
    HttpUser,
    TaskSet,
    task,
    between,
    events,
)
from locust.exception import StopUser
from utils import make_authorized_header_for_app_integration, create_test_gpg_keypair, get_change_request_payload


FEEDER_HOST = os.getenv('FEEDER_HOST', '127.0.0.1')
FEEDER_BIND_PORT = os.getenv('FEEDER_BIND_PORT', 5555)
FEEDER_ADDR = f'tcp://{FEEDER_HOST}:{FEEDER_BIND_PORT}'
TAMWINI_EXT_APP_SECRET_KEY = os.getenv('TAMWINI_EXT_APP_SECRET_KEY', '')
TAMWINI_EXT_APP_UUID = os.getenv('TAMWINI_EXT_APP_UUID', '')
API_USER_TOKEN = os.getenv('API_USER_TOKEN', '')
COMPANY_TOKEN = os.getenv('COMPANY_TOKEN', '')


class ZMQRequester:
    def __init__(self, address="tcp://127.0.0.1:5555"):
        context = zmq.Context()
        self.socket = context.socket(zmq.REQ)
        self.socket.connect(address)
        logging.info("zmq consumer initialized")

    def await_data(self):
        logging.info("Worker available")
        self.socket.send_json({'available': True})
        return self.socket.recv_json()

    def start_tests(self):
        logging.info("A new test is starting")
        self.socket.send_json({'start': True})
        return self.socket.recv_json()


@events.test_start.add_listener
def on_test_start(**kwargs):
    zmq_consumer = ZMQRequester(FEEDER_ADDR)
    zmq_consumer.start_tests()



class TamwiniUser(HttpUser):
    wait_time = between(1, 5)

    def on_start(self):
        # load single hh per user
        self.zmq_consumer = ZMQRequester(FEEDER_ADDR)
        data = self.zmq_consumer.await_data()
        if data == {}:
            logging.info("No more data. Stopping user.")
            raise StopUser()
        else:
            self.household = data

        self.pgp_pair = create_test_gpg_keypair(self.household['pds_card_number'])

    @task
    class TamwiniRequestFlow(TaskSet):

        def on_start(self):
            self.household = self.user.household
            self.pgp_pair = self.user.pgp_pair
            self.otp = '1234'
            self.password = 'abcdefgh1234'

        @property
        def _get_headers(self):
            return make_authorized_header_for_app_integration(TAMWINI_EXT_APP_SECRET_KEY, TAMWINI_EXT_APP_UUID)

        @property
        def _get_api_headers(self):
            headers = self._get_headers
            headers.update({
                'scope-authorization': 'Bearer {}/{}'.format(COMPANY_TOKEN, API_USER_TOKEN)
            })
            return headers


        @task(5)
        def registration_only_tasks(self):
            self._registration_tasks()

        @task(2)
        @task
        def register_and_create_request_tasks(self):
            try:
                error = False
                self._registration_tasks()
            except Exception:
                error = True

            if not error:
                self._change_request_tasks()

        def _registration_tasks(self):
            # Register
            data = copy.deepcopy(self.household)
            del data['household_uuid']
            response = self.client.post(
                '/api/beneficiary-access-gateway/auth/pds-uid/',
                data=data,
                headers=self._get_headers,
            )
            json_resp = response.json()
            self.household['household_uuid_hex'] = json_resp['household_uuid']
            assert self.household['household_uuid_hex'] == self.household['household_uuid'].replace('-', '')

            # Set mobile
            data = {
                'household_uuid': self.household['household_uuid'],
                'mobile_number': self.household['phone_number'],
            }
            response = self.client.post(
                '/api/beneficiary-access-gateway/auth/set-mobile/',
                data=data,
                headers=self._get_headers,
            )
            assert response.status_code == 200
            assert self.household['phone_number'] in response.json()['message']

            # Request and verify otp
            data = {
                'case_number': self.household['pds_card_number'],
                'mobile_number': self.household['phone_number']
            }
            response = self.client.post(
                '/api/beneficiary-access-gateway/auth/request-otp/',
                data=data,
                headers=self._get_headers,
            )
            assert response.status_code == 200

            data = {
                'otp_code': self.otp,
                'case_number': self.household['pds_card_number'],
            }
            response = self.client.post(
                '/api/beneficiary-access-gateway/auth/verify-otp/',
                data=data,
                headers=self._get_headers,
            )
            assert response.status_code == 200

            # set password
            data = {
                'case_number': self.household['pds_card_number'],
                'client_uuid': self.household['household_uuid'],
                'client_pgp_key': self.pgp_pair[0],
                'password': self.password,
            }
            response = self.client.post(
                '/api/beneficiary-access-gateway/auth/set-password/',
                data=data,
                headers=self._get_headers,
            )
            assert response.status_code == 200

        def _change_request_tasks(self):
            # api/beneficiary-access-gateway/household-members/
            headers = self._get_api_headers
            headers.update({
                'x-scope-client-uuid': self.household['household_uuid'],
                'x-scope-client-pin': self.password,
            })
            self.client.get(
                '/api/beneficiary-access-gateway/household-members/',
                headers=headers,
            )

            # api/beneficiary-access-gateway/change-request/create/
            data = get_change_request_payload()
            data['requester']['phone_number'] = self.household['phone_number']
            data['requester']['family_number'] = self.household['family_number']
            data['requester']['phone_number'] = self.household['phone_number']
            data['member_identification']['pds_number'] = self.household['pds_card_number']
            data['member_identification']['unified_id'] = f"1{self.household['unified_id_card_number']}"
            data['member_identification']['family_number'] = self.household['family_number']
            data['parent_identification']['pds_number'] = self.household['pds_card_number']
            data['parent_identification']['unified_id'] = self.household['unified_id_card_number']
            data['parent_identification']['family_number'] = self.household['family_number']

            self.client.post(
                '/api/beneficiary-access-gateway/change-request/create/',
                data=json.dumps(data),
                headers=headers,
            )

            # api/beneficiary-access-gateway/change-request/list/
            self.client.get(
                '/api/beneficiary-access-gateway/change-request/list/',
                headers=headers,
            )
