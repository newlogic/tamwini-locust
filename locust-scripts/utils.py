
import uuid
import time
import pyotp
import base64
import gnupg
import os
import json


DEFAULT_GNUPG_OPTIONS = [
    "--ignore-time-conflict",
    "--ignore-valid-from",
    "--always-trust",
]


def make_authorized_header_for_app_integration(secret_key, ext_app_uuid):
    totp = pyotp.TOTP(secret_key, interval=300)

    token = 'Basic {}'.format(
        base64.b64encode(
            '{}:{}'.format(
                ext_app_uuid,
                totp.now()
            ).encode('utf-8')
        ).decode('utf-8')
    )

    return {'scope-totp-authorization': token}


def get_gnupg_home():
    path = os.path.expanduser('~/credentials/bag_pgp_test')
    return os.path.join(path, str(uuid.uuid4().hex))


def gpg_constructor(gnupghome: str, options=None, ensure_gnupghome_exists=True, **kwargs):
    """
    Simple wrapper for GPG class
    """
    if ensure_gnupghome_exists:
        if not os.path.exists(gnupghome):
            os.makedirs(gnupghome)

    return gnupg.GPG(
        gnupghome=gnupghome,
        options=options,
        **kwargs
    )


def create_gpg_instance(options=None, **kwargs):
    if not options:
        options = DEFAULT_GNUPG_OPTIONS
    return gpg_constructor(
        gnupghome=get_gnupg_home(),
        options=options,
        **kwargs
    )


def create_test_gpg_keypair(user):
    """
    A GPG keypair with the following properties:
    - Created 1 hour ahead of the system clock to ensure time
      validation is not enforced anywhere
    """
    current_seconds_since_epoch = int(time.time())
    future_time = current_seconds_since_epoch + 3600
    gpg = create_gpg_instance(
        options=DEFAULT_GNUPG_OPTIONS
    )
    key_input_data = gpg.gen_key_input(
        name_email=f'{user}@wfp.org',
        passphrase='secret',
        expire_date="1d",
    )
    key = gpg.gen_key(key_input_data)
    public_key = gpg.export_keys(key.fingerprint)
    private_key = gpg.export_keys(key.fingerprint, secret=True, passphrase='secret')
    return public_key, private_key

def get_change_request_payload():
    path = os.path.join(os.path.dirname(__file__), 'add_member_request_payload.json')
    with open(path, 'rb') as f:
        c = json.load(f)
    return c
