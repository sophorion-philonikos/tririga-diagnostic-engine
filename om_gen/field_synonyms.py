"""BO-scoped field synonym resolver for om_gen intent.

Phrase keys are lowercase; longest match wins.
Explicit tri* / cst* field names always win. Unknown phrases fail closed.

Add synonyms in _GLOBAL or _BY_BO — seed from corpus PField/TrgtFld + OOB labels.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

# phrase (lowercase) → (field_name, default_section)
_GLOBAL: Dict[str, Tuple[str, str]] = {
    # Name / id
    'name': ('triNameTX', 'General'),
    'name field': ('triNameTX', 'General'),
    'the name': ('triNameTX', 'General'),
    'the name field': ('triNameTX', 'General'),
    'building name': ('triNameTX', 'General'),
    'building name field': ('triNameTX', 'General'),
    'building\'s name': ('triNameTX', 'General'),
    'building\'s name field': ('triNameTX', 'General'),
    'id': ('triIdTX', 'General'),
    'id field': ('triIdTX', 'General'),
    'building id': ('triIdTX', 'General'),
    'location id': ('triIdTX', 'General'),
    'record id': ('triRecordIdSY', 'RecordInformation'),
    'control number': ('triControlNumberCN', 'General'),
    # Status / form
    'form name': ('triFormNameSY', 'RecordInformation'),
    'form label': ('triFormLabelSY', 'RecordInformation'),
    'status': ('triStatusTX', 'RecordInformation'),
    'status text': ('triStatusTX', 'RecordInformation'),
    'status field': ('triStatusTX', 'RecordInformation'),
    'status classification': ('triStatusCL', 'RecordInformation'),
    'fed status': ('triFedStatusCL', 'RecordInformation'),
    # RPIM / ops
    'operational status indicator': ('triRPAOperationalStatusCodeCL', 'triRPIMRealPropertyAsset'),
    'operational status': ('triRPAOperationalStatusCodeCL', 'triRPIMRealPropertyAsset'),
    'using rpim': ('triUsingRPIMBL', 'triRPIMRealPropertyAsset'),
    'using frpp': ('triUsingFRPPBL', 'triRPIMRealPropertyAsset'),
    'lease authority': ('triLeaseAuthorityCL', 'General'),
    'legal interest': ('triLegalInterestCL', 'General'),
    'mission dependency': ('triMissionDependencyCL', 'General'),
    # Messaging / description
    'user message': ('triUserMessageTX', 'RecordInformation'),
    'description': ('triDescriptionTX', 'General'),
    'description field': ('triDescriptionTX', 'General'),
    # Address (IBM Building OSLC / common OOB)
    'address': ('triAddressTX', 'General'),
    'street address': ('triAddressTX', 'General'),
    'city': ('triCityTX', 'General'),
    'state': ('triStateProvTX', 'General'),
    'state province': ('triStateProvTX', 'General'),
    'zip': ('triZipPostalTX', 'General'),
    'postal code': ('triZipPostalTX', 'General'),
    'county': ('triCountyTX', 'General'),
    'country': ('triCountryTX', 'General'),
    # Dates / misc high-frequency corpus
    'start date': ('triStartDA', 'General'),
    'end date': ('triEndDA', 'General'),
    'expiration date': ('triExpirationDA', 'General'),
    'due date': ('triDueDA', 'General'),
    'time zone': ('triTimeZonesCL', 'RecordInformation'),
    'time zones': ('triTimeZonesCL', 'RecordInformation'),
    'area': ('triAreaUO', 'General'),
    'currency': ('triCurrencyUO', 'General'),
    'geography name': ('GeographyName', 'General'),
    'location name': ('LocationName', 'General'),
    'org name': ('OrgName', 'General'),
    'user account': ('User Account', 'General'),
}

_BY_BO: Dict[Tuple[str, str], Dict[str, Tuple[str, str]]] = {
    ('Location', 'triBuilding'): {
        'name': ('triNameTX', 'General'),
        'name field': ('triNameTX', 'General'),
        'building name': ('triNameTX', 'General'),
        'building\'s name': ('triNameTX', 'General'),
        'building\'s name field': ('triNameTX', 'General'),
        'building id': ('triIdTX', 'General'),
        'operational status indicator': ('triRPAOperationalStatusCodeCL', 'triRPIMRealPropertyAsset'),
        'building class': ('triBuildingClassCL', 'General'),
    },
    ('Location', 'triLand'): {
        'name': ('triNameTX', 'General'),
        'operational status indicator': ('triRPAOperationalStatusCodeCL', 'triRPIMRealPropertyAsset'),
        'operational status': ('triRPAOperationalStatusCodeCL', 'triRPIMRealPropertyAsset'),
    },
    ('Location', 'triSpace'): {
        'name': ('triNameTX', 'General'),
    },
    ('Location', 'triProperty'): {
        'name': ('triNameTX', 'General'),
    },
    ('Location', 'triFloor'): {
        'name': ('triNameTX', 'General'),
    },
    ('triPeople', 'triPeople'): {
        'name': ('triNameTX', 'General'),
        'user account': ('User Account', 'General'),
    },
    ('triProject', 'triCapitalProject'): {
        'name': ('triNameTX', 'General'),
    },
    ('triContract', 'triRealEstateContract'): {
        'name': ('triNameTX', 'General'),
        'contract id': ('triContractIdTX', 'General'),
    },
}


def known_field_phrases(module: str = '', bo: str = '') -> Tuple[str, ...]:
    phrases = set(_GLOBAL.keys())
    if module and bo:
        phrases |= set(_BY_BO.get((module, bo), {}).keys())
    return tuple(sorted(phrases))


def resolve_field(
    phrase: str,
    *,
    module: str = '',
    bo: str = '',
) -> Optional[Tuple[str, str]]:
    """Return (field_name, section) or None if unresolved."""
    raw = (phrase or '').strip()
    if not raw:
        return None

    if raw.startswith('tri') or raw.startswith('cst') or raw in (
        'GeographyName', 'LocationName', 'OrgName', 'User Account',
    ):
        section = 'General'
        if raw.endswith('SY') or raw in ('triStatusTX', 'triUserMessageTX', 'triRecordIdSY'):
            section = 'RecordInformation'
        if raw in ('triRPAOperationalStatusCodeCL', 'triUsingRPIMBL', 'triUsingFRPPBL'):
            section = 'triRPIMRealPropertyAsset'
        return raw, section

    key = raw.lower().strip()
    key = key.replace("'s ", ' ').replace('’s ', ' ')
    key = ' '.join(key.split())

    if module and bo:
        scoped = _BY_BO.get((module, bo), {})
        if key in scoped:
            return scoped[key]

    if key in _GLOBAL:
        return _GLOBAL[key]

    if key.endswith(' field'):
        return resolve_field(key[:-6].strip(), module=module, bo=bo)

    return None
