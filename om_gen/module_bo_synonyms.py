"""Module/BO and event synonym catalogs for om_gen intent.

Phrase keys are lowercase; longest match wins.
Add new synonyms here — never invent unresolved phrases at parse time.

Corpus: 55 Header Module/BO pairs across 158 Workflow_*.xml.
Events: corpus Header/Start/Trigger EventNames + IBM TAP naming examples.
"""

from __future__ import annotations

import re
from typing import Dict, FrozenSet, Optional, Tuple

# ---------------------------------------------------------------------------
# Module / BO — phrase → (module, bo)
# ---------------------------------------------------------------------------
# Exact BO tokens also resolve via find when prose names triBuilding etc.

MODULE_BO_PHRASES: Dict[str, Tuple[str, str]] = {
    # Location
    'building': ('Location', 'triBuilding'),
    'building record': ('Location', 'triBuilding'),
    'building records': ('Location', 'triBuilding'),
    'a building': ('Location', 'triBuilding'),
    'the building': ('Location', 'triBuilding'),
    'the building record': ('Location', 'triBuilding'),
    'buildings': ('Location', 'triBuilding'),
    'tribuilding': ('Location', 'triBuilding'),
    'land': ('Location', 'triLand'),
    'land record': ('Location', 'triLand'),
    'land records': ('Location', 'triLand'),
    'the land': ('Location', 'triLand'),
    'triland': ('Location', 'triLand'),
    'space': ('Location', 'triSpace'),
    'space record': ('Location', 'triSpace'),
    'spaces': ('Location', 'triSpace'),
    'trispace': ('Location', 'triSpace'),
    'property': ('Location', 'triProperty'),
    'property record': ('Location', 'triProperty'),
    'properties': ('Location', 'triProperty'),
    'triproperty': ('Location', 'triProperty'),
    'floor': ('Location', 'triFloor'),
    'floor record': ('Location', 'triFloor'),
    'floors': ('Location', 'triFloor'),
    'trifloor': ('Location', 'triFloor'),
    # People
    'people': ('triPeople', 'triPeople'),
    'person': ('triPeople', 'triPeople'),
    'persons': ('triPeople', 'triPeople'),
    'employee': ('triPeople', 'triPeople'),
    'employees': ('triPeople', 'triPeople'),
    'tripeople': ('triPeople', 'triPeople'),
    'my profile': ('triPeople', 'My Profile'),
    'profile': ('triPeople', 'My Profile'),
    # Project
    'capital project': ('triProject', 'triCapitalProject'),
    'capital projects': ('triProject', 'triCapitalProject'),
    'project': ('triProject', 'triCapitalProject'),
    'projects': ('triProject', 'triCapitalProject'),
    'tricapitalproject': ('triProject', 'triCapitalProject'),
    # Contract
    'real estate contract': ('triContract', 'triRealEstateContract'),
    'real estate contracts': ('triContract', 'triRealEstateContract'),
    'lease contract': ('triContract', 'triRealEstateContract'),
    'lease': ('triContract', 'triRealEstateContract'),
    'trirealestatecontract': ('triContract', 'triRealEstateContract'),
    'lease abstract': ('triContract', 'triLeaseAbstract'),
    'asset lease': ('triContract', 'triAssetLease'),
    'blanket purchase order': ('triContract', 'triBlanketPurchaseOrder'),
    # Payment / cost
    'payment schedule': ('triPayment', 'triPaymentSchedule'),
    'payment line item': ('triCostItem', 'triPaymentLineItem'),
    'payment release': ('triPayment', 'triPaymentRelease'),
    # Integration / helper
    'integration': ('triIntegration', 'triIntegration'),
    'integration notification': ('triIntegration', 'triIntegrationNotification'),
    'patch helper': ('triHelper', 'triPatchHelper'),
    'notification helper': ('triHelper', 'triNotificationHelper'),
    # Proposal / task
    'bid document': ('triProposal', 'triBidDocument'),
    'work task': ('triTask', 'triWorkTask'),
    'submittal task': ('triTask', 'triSubmittalTask'),
}

# All corpus Module/BO pairs (exact lookup helpers)
CORPUS_MODULE_BO: FrozenSet[Tuple[str, str]] = frozenset({
    ('triProject', 'triCapitalProject'),
    ('triHelper', 'triPatchHelper'),
    ('Location', 'triBuilding'),
    ('triPeople', 'My Profile'),
    ('triPeople', 'triPeople'),
    ('triContract', 'triRealEstateContract'),
    ('triContract', 'cstPlannedPropertyTransaction'),
    ('triIntegration', 'triIntegration'),
    ('triCostItem', 'triPaymentLineItem'),
    ('Location', 'triLand'),
    ('Location', 'triProperty'),
    ('triContract', 'triBlanketPurchaseOrder'),
    ('triHelper', 'triNotificationHelper'),
    ('triIntegration', 'triIntegrationNotification'),
    ('triPayment', 'triPaymentSchedule'),
    ('Location', 'triSpace'),
    ('triProposal', 'triBidDocument'),
    ('Classification', 'triBuildingClass'),
    ('Classification', 'triChecklistType'),
    ('Classification', 'triFinancialCategory'),
    ('Classification', 'triLandPredominantUseCode'),
    ('Classification', 'triPriority'),
    ('Classification', 'triRPAInterestTypeCode'),
    ('Classification', 'triRPATypeCode'),
    ('Classification', 'triTransactionBuildingClass'),
    ('Location', 'Location'),
    ('Location', 'cstBuildingDTO'),
    ('Location', 'triFloor'),
    ('triContract', 'cstRealEstateContractDTO'),
    ('triContract', 'cstRentForecastLineItem'),
    ('triContract', 'triAssetLease'),
    ('triContract', 'triLeaseAbstract'),
    ('triContract', 'triStandardContractChangeOrder'),
    ('triGovernment', 'triRPIMAssetAllocation'),
    ('triGovernment', 'triRPIMFunding'),
    ('triGovernment', 'triRPIMInspectionItem'),
    ('triGovernment', 'triRPIMProjectDetail'),
    ('triGovernment', 'triRPIMPropertyAction'),
    ('triGovernment', 'triRPIMRealPropertyAsset'),
    ('triGovernment', 'triRPIMRealPropertyNetwork'),
    ('triGovernment', 'triRPIMRestriction'),
    ('triHelper', 'cstDataLinkHelper'),
    ('triHelper', 'triLeaseJournalEntryCreationHelper'),
    ('triHelper', 'triLeaseSummaryHelper'),
    ('triIntegration', 'triIntegrationInstance'),
    ('triPayment', 'triPaymentRelease'),
    ('triPayment', 'triVoidPayments'),
    ('triProposal', 'triBidResponse'),
    ('triProposal', 'triRFP'),
    ('triProposal', 'triRFPResponse'),
    ('triTask', 'triConditionAssessmentWorkTask'),
    ('triTask', 'triInventoryCountWorkTask'),
    ('triTask', 'triKeyWorkTask'),
    ('triTask', 'triSubmittalTask'),
    ('triTask', 'triWorkTask'),
})

# ---------------------------------------------------------------------------
# Events — phrase → EventName (longest match wins)
# ---------------------------------------------------------------------------
EVENT_SYNONYMS: Dict[str, str] = {
    # triSave
    'save': 'triSave',
    'on save': 'triSave',
    'tri save': 'triSave',
    'trisave': 'triSave',
    'clicks save': 'triSave',
    'click save': 'triSave',
    'clicking save': 'triSave',
    'when the user clicks save': 'triSave',
    'when user clicks save': 'triSave',
    'the user clicks save': 'triSave',
    'user clicks save': 'triSave',
    'saves the record': 'triSave',
    'save the record': 'triSave',
    # Pre-Create
    'pre-create': 'Pre-Create',
    'pre create': 'Pre-Create',
    'precreate': 'Pre-Create',
    'on pre-create': 'Pre-Create',
    'on pre create': 'Pre-Create',
    # Create / draft
    'create draft': 'triCreateDraft',
    'create-draft': 'triCreateDraft',
    'tricreatedraft': 'triCreateDraft',
    'tri create draft': 'triCreateDraft',
    # Activate / retire / revise / complete / issue / review
    'activate': 'triActivate',
    'activates': 'triActivate',
    'on activate': 'triActivate',
    'triactivate': 'triActivate',
    'retire': 'triRetire',
    'retires': 'triRetire',
    'on retire': 'triRetire',
    'triretire': 'triRetire',
    'revise': 'triRevise',
    'revises': 'triRevise',
    'revision': 'triRevise',
    'revision in progress': 'triRevise',
    'trirevise': 'triRevise',
    'complete': 'triComplete',
    'completed': 'triComplete',
    'tricomplete': 'triComplete',
    'issue': 'triIssue',
    'issued': 'triIssue',
    'triissue': 'triIssue',
    'review': 'triReview',
    'trireview': 'triReview',
    # Copy / calculate / create / update / delete
    'copy': 'triCopy',
    'tricopy': 'triCopy',
    'on copy': 'triCopy',
    'calculate': 'triCalculate',
    'tricalculate': 'triCalculate',
    'on calculate': 'triCalculate',
    'tri create': 'triCreate',
    'tricreate': 'triCreate',
    'update': 'triUpdate',
    'triupdate': 'triUpdate',
    'delete': 'triDelete',
    'tridelete': 'triDelete',
    # Associate
    'associate': 'Associate',
    'on associate': 'Associate',
    'de-associate': 'De-Associate',
    'deassociate': 'De-Associate',
    # Misc corpus / docs
    'send': 'SEND',
    'unretire': 'triUnretire',
    'refresh': 'triRefresh',
    'final approval': 'triFinalApprovalHidden',
}

# Explicit EventName tokens accepted as-is (case-sensitive match after strip)
KNOWN_EVENT_TOKENS: FrozenSet[str] = frozenset({
    'triSave', 'triCreate', 'triCreateDraft', 'triActivate', 'triRetire',
    'triRevise', 'triComplete', 'triIssue', 'triReview', 'triCopy',
    'triCalculate', 'triUpdate', 'triDelete', 'triUnretire', 'triRefresh',
    'triRemove', 'triExecute', 'Pre-Create', 'Pre-Delete', 'Associate',
    'De-Associate', 'SEND', 'CREATE', 'SCHEVENTSTART', 'NOTIFY',
    'SCHEDULE', 'UNSCHEDULE', 'triFinalApprovalHidden', 'triRetireHidden',
    'triPublishSecurity', 'triValidateContacts', 'triCreateTemplate',
})


def resolve_module_bo(phrase: str) -> Optional[Tuple[str, str]]:
    """Return (module, bo) from a plain-English phrase, or None."""
    key = ' '.join((phrase or '').lower().split())
    if not key:
        return None
    if key in MODULE_BO_PHRASES:
        return MODULE_BO_PHRASES[key]
    return None


def find_module_bo_in_text(text: str) -> Optional[Tuple[str, str, str]]:
    """Scan text for a Module/BO phrase. Return (module, bo, matched_span) or None."""
    lower = (text or '').lower()
    best: Optional[Tuple[int, int, str, str, str]] = None
    for phrase, (mod, bob) in sorted(MODULE_BO_PHRASES.items(), key=lambda x: -len(x[0])):
        idx = lower.find(phrase)
        if idx < 0:
            continue
        before = lower[idx - 1] if idx > 0 else ' '
        after_i = idx + len(phrase)
        after = lower[after_i] if after_i < len(lower) else ' '
        if before.isalnum() or after.isalnum():
            continue
        cand = (idx, len(phrase), mod, bob, text[idx:after_i])
        if best is None or cand[1] > best[1] or (cand[1] == best[1] and cand[0] < best[0]):
            best = cand
    if best is None:
        return None
    return best[2], best[3], best[4]


def resolve_event(phrase: str) -> Optional[str]:
    raw = (phrase or '').strip()
    if not raw:
        return None
    if raw in KNOWN_EVENT_TOKENS:
        return raw
    if re.match(r'^tri[A-Za-z0-9]+$', raw):
        return raw
    key = ' '.join(raw.lower().split())
    return EVENT_SYNONYMS.get(key)


def find_event_in_text(text: str) -> Optional[Tuple[str, str]]:
    """Return (event_name, matched_span) from prose, or None."""
    raw = text or ''
    lower = ' '.join(raw.lower().split())
    # Longer phrases first
    for phrase, event in sorted(EVENT_SYNONYMS.items(), key=lambda x: -len(x[0])):
        if phrase in lower:
            return event, phrase
    # Bare known tokens (preserve original casing from list)
    lower_raw = raw.lower()
    for token in sorted(KNOWN_EVENT_TOKENS, key=len, reverse=True):
        if token.lower() in lower_raw:
            return token, token
    return None
