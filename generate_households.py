import csv
import uuid
from argparse import ArgumentParser
from datetime import datetime
import random
import time

import django
import pyotp

django.setup()
from django.conf import settings
from django.db import transaction

from foodnet.apps.beneficiary_access_gateway.models.access import (
    AccessPermissions,
)
from foodnet.apps.external_integrations.models import ExternalAppIntegration
from foodnet.apps.registration.constants import UNIFIED_ID_TYPE_NAME, PDS_TYPE_NAME
from foodnet.apps.registration.factories import (
    DocumentFactory,
    HouseholdFactory,
    PersonForHouseholdFactory,
    DocumentTypeFactory,
    FingerPrintFactory,
    IrisFactory,
)
from foodnet.apps.registration.models import DocumentType, Person, Document, FingerPrint, Iris
from foodnet.apps.security.roles import (
    add_role_beneficiary_access_gateway_api_user,
)
from foodnet.apps.wfp.models import (
    ApiUserProfile,
    Company,
    Office,
)
from geo.models import Location
from foodnet.lib.middleware import (
    activate_script_user,
    get_current_user,
)


class NoChangesAppliedException(Exception):
    pass


def timing_function(function_to_time):
    """
    Outputs the time a function takes to execute.
    """

    def wrapper(*args, **kwargs):
        t1 = datetime.now()
        function_to_time(*args, **kwargs)
        t2 = datetime.now()
        print("Time it took to execute: {}\n".format(t2 - t1))
        print("Date executed: {}".format(datetime.now().strftime("%A %d-%B-%Y %H:%M:%S %p")))
        print('-' * 80)

    return wrapper


def generate_households(office, n_households=10000, members=4, offset=0):
    locations = Location.objects.filter(country=office.country).all()[:10]
    registrar_user = get_current_user()
    unified_doc = DocumentTypeFactory(office=office, type=UNIFIED_ID_TYPE_NAME)
    pds_doc = DocumentTypeFactory(office=office, type=PDS_TYPE_NAME)
    total_time = 0

    with open('households.csv', 'a', newline='') as csvfile:
        fieldnames = ['household_uuid', 'pds_card_number', 'unified_id_card_number', 'family_number', 'phone_number']
        households_csv = csv.DictWriter(csvfile, fieldnames=fieldnames)
        if offset == 0:
            households_csv.writeheader()
        for idx in range(n_households):
            idx_with_offset = idx + offset
            docs = list()
            start_time = time.time()
            data = {
                'pds_card_number': f'00{idx_with_offset}',
                'unified_id_card_number':  f'50{idx_with_offset}',
                'family_number':  f'90{idx_with_offset}',
            }
            print(f"Creating household {data['pds_card_number']}")
            additional = {
                'family_number': data['family_number'],
            }
            location = random.choice(locations)
            household = HouseholdFactory.create(
                name=data['pds_card_number'],
                office=office,
                claimed_member_count=members,
                registration_user=registrar_user,
                additional_fields=additional,
            )
            data['household_uuid'] = str(uuid.UUID(str(household.uuid)))

            fps = list()
            irises = list()
            for member in range(members):
                person = PersonForHouseholdFactory.create(
                    household=household,
                    location=location,
                    add_photo=True,
                    household_role=Person.RELATION_HEAD if member == 0 else Person.RELATION_BROTHER_SISTER,
                    is_principal=True if member == 0 else False,
                    additional_fields=additional,
                )
                fps.append(FingerPrintFactory.build(person=person))
                irises.append(IrisFactory.build(person=person))
                docs.append(DocumentFactory.build(
                    person=person,
                    document_type=unified_doc,
                    document_num=f"{data['unified_id_card_number']}-{member}"
                ))
                if person.household_role == Person.RELATION_HEAD:
                    data['phone_number'] = person.mobile_number
                    docs.append(DocumentFactory.build(
                        person=person,
                        document_type=pds_doc,
                        document_num=f"{data['pds_card_number']}"
                    ))

            Document.objects.bulk_create(docs)
            FingerPrint.objects.bulk_create(fps)
            Iris.objects.bulk_create(irises)

            data['unified_id_card_number'] = f"{data['unified_id_card_number']}-0"

            households_csv.writerow(data)

            end_time = time.time()
            elapsed = end_time - start_time
            total_time += elapsed
            hh_idx = idx + 1
            remaining_time = (total_time / hh_idx) * (n_households - hh_idx)
            print(f'Estimated time remaining: {time.strftime("%H:%M:%S", time.gmtime(remaining_time))}')


def generate_external_app():
    ext_app_permissions, _ = AccessPermissions.objects.get_or_create(
        view_ecard_transactions=True,
        set_mobile_number=True,
        view_household_members=True,
        submit_change_requests=True,
    )

    external_app_integration, _ = ExternalAppIntegration.objects.get_or_create(
        app_name='Load test app',
        permissions=ext_app_permissions,
        defaults=(dict(
            pin_session_minutes=30,
            registration_expiry_days=90,
            secret_key=pyotp.random_base32(),
        )),
    )

    return external_app_integration


def generate_api_user(office):
    company, _ = Company.objects.get_or_create(name='Tamwini Company')
    api_user_profile, _ = ApiUserProfile.objects.get_or_create(
        username=settings.BENEFICIARY_ACCESS_GATEWAY_API_USERNAMES[office.slug],
        defaults=(dict(
            first_name="Tamwini API User {}".format(office.slug),
            last_name="Tamwini Family",
            country_office=office,
            api_token="tamwini-api-user-token",
            company=company,
        )),
    )
    add_role_beneficiary_access_gateway_api_user(api_user_profile.user, office)

    # Beneficiary authentication & client application
    unified_id_document_type, _ = DocumentType.objects.get_or_create(
        office=office,
        type=UNIFIED_ID_TYPE_NAME,
        defaults=dict(regex=".*"))

    return api_user_profile


def run_generate(office, n_households, n_members, offset):
    external_app = generate_external_app()
    api_user = generate_api_user(office)
    generate_households(office, n_households, n_members, offset)
    print(f"External App Secret: {external_app.secret_key}")
    print(f"External App UUID: {external_app.uuid}")
    print(f"API user token: {api_user.api_token}")
    print(f"Company token: {api_user.company.api_token}")


@timing_function
def main(args):
    office_slug = args.office
    n_households = args.households
    n_members = args.members
    apply_changes = args.apply_changes
    offset = args.offset
    office = Office.objects.get(slug=office_slug)

    if apply_changes:
        activate_script_user()
        run_generate(office, n_households, n_members, offset)
    else:
        try:
            with transaction.atomic():
                run_generate(office, n_households, n_members, offset)
                if not apply_changes:
                    raise NoChangesAppliedException()
        except NoChangesAppliedException:
            print('This was a DRY-RUN. Nothing has been changed!')


if __name__ == '__main__':
    print("SCOPE-15530: Create Households for Load testing")
    print('-' * 80)
    parser = ArgumentParser()
    parser.add_argument(
        '--office',
        dest='office',
        type=str,
        default='lb-co',
        help='Office to create households for',
    )
    parser.add_argument(
        '--households',
        dest='households',
        type=int,
        default=10000,
        help='Number of households to be generated',
    )
    parser.add_argument(
        '--members',
        dest='members',
        type=int,
        default=4,
        help='Number of persons per household to be generated',
    )
    parser.add_argument(
        '--apply-changes',
        dest='apply_changes',
        action='store_true',
        help='Apply changes made by this script',
    )
    parser.add_argument(
        '--offset',
        dest='offset',
        type=int,
        default=0,
        help='Offset to start hh name index. Used for cases when HH generation has to be restarted',
    )

    args = parser.parse_args()
    main(args)
    print('DONE.')
