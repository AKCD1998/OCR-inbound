"""Narrow correction eligibility; historical field diagnostics are not goods roles.

Only exact, unapproved diagnostic schemas are removed on a disposable copy
before the frozen protection rule runs. Their candidate values are never used
as answers. Real row metadata and all semantic/unknown relationships survive.
"""
from __future__ import annotations

from copy import deepcopy
import math
import re

VERSION = 'document-ai-correction-row-eligibility.v1'
BONUS = re.compile(r'\b(?:bonus|free\s*goods?|foc|free\s*item)\b|ของแถม|สินค้าแถม', re.I)
FIELDS = frozenset(('description', 'quantity', 'quantity_partial', 'unit', 'packing',
                    'lot', 'mfg_date', 'exp_date', 'supplier_code', 'unit_price', 'amount', 'discount'))
# These are source-field objects, not rows. Unexpected payloads abstain; this
# list does not make any value in a historical field authoritative.
FIELD_KEYS = frozenset(('bbox', 'confidence', 'engine', 'engines', 'normalized_value',
    'raw_value', 'review_flags', 'source_spans', 'token_ids', 'interpretation_basis',
    'source_bbox_kind', 'interpretation_status', 'proposed_normalized_value'))


def _field(value):
    if not (type(value) is dict and bool(value) and set(value) <= FIELD_KEYS
            and ('raw_value' in value or 'normalized_value' in value)):
        return False
    # Historical answers are opaque *scalar* literals, never row-shaped
    # objects hidden under an otherwise familiar source-field key.
    return all(value.get(key) is None or (type(value[key]) in (str, int, float)
               and (type(value[key]) is not float or math.isfinite(value[key])))
               for key in ('raw_value', 'normalized_value', 'proposed_normalized_value'))


def _field_role(value):
    return type(value) is str and value in FIELDS


def _diagnostic(relation):
    """Exact discriminator/schema/approval flags; unknown payloads stay protected."""
    if type(relation) is not dict or type(relation.get('type')) is not str:
        return False
    kind = relation['type']
    if kind in ('adaptive_field_conflict', 'supplier_pattern_conflicting_source_field'):
        previous, flag = ('previous', 'source_association_approved') if kind == 'adaptive_field_conflict' else ('kept', 'automatic_overwrite_allowed')
        return (set(relation) == {'type', 'field', previous, 'candidate', flag}
                and _field_role(relation.get('field')) and relation.get(flag) is False
                and _field(relation[previous]) and _field(relation['candidate']))
    if kind == 'adaptive_bounded_field_candidates':
        return (set(relation) == {'type', 'field', 'candidates', 'association_verified'}
                and _field_role(relation.get('field')) and relation.get('association_verified') is False
                and type(relation['candidates']) is list and len(relation['candidates']) >= 2
                and all(_field(value) for value in relation['candidates']))
    if kind == 'amount_unparsed_numeric_evidence':
        return (set(relation) == {'type', 'candidates'} and type(relation['candidates']) is list
                and bool(relation['candidates']) and all(_field(value) for value in relation['candidates']))
    return False


def assess_row(row, rules):
    """Return eligibility/audit without changing any part of ``row`` or rules."""
    audit = {'contract': VERSION, 'eligible': False, 'ignored_diagnostic_types': [],
             'ignored_diagnostics': [], 'blocked_relationship_types': [], 'reasons': [],
             'historical_candidate_values_used': False, 'row_metadata_modified': False}
    if type(row) is not dict:
        audit['reasons'].append('ROW_OBJECT_REQUIRED')
        return audit
    view = deepcopy(row)
    relations = row.get('relationships')
    if relations is not None and type(relations) is not list:
        audit['reasons'].append('MALFORMED_RELATIONSHIP_COLLECTION')
        return audit
    retained = []
    for index, relation in enumerate(relations or []):
        if _diagnostic(relation):
            kind = relation['type']
            audit['ignored_diagnostic_types'].append(kind)
            audit['ignored_diagnostics'].append({'index': index, 'type': kind})
        else:
            retained.append(deepcopy(relation))
            kind = relation.get('type') if type(relation) is dict else None
            audit['blocked_relationship_types'].append(kind if type(kind) is str else 'MALFORMED')
    if relations is not None:
        view['relationships'] = retained
    if retained:
        audit['reasons'].append('SEMANTIC_UNKNOWN_OR_MALFORMED_RELATIONSHIP')
    try:
        frozen_protected = bool(rules._protected(view))
    except (KeyError, TypeError, ValueError, AttributeError):
        audit['reasons'].append('FROZEN_PROTECTION_COULD_NOT_ESTABLISH_ELIGIBILITY')
        return audit
    audit['frozen_protected_after_diagnostic_filter'] = frozen_protected
    if frozen_protected:
        audit['reasons'].append('FROZEN_ROW_PROTECTION')
    fields = row.get('fields') or {}
    description = fields.get('description') or {} if type(fields) is dict else None
    if type(description) is not dict:
        audit['reasons'].append('MALFORMED_SOURCE_DESCRIPTION')
        return audit
    bonus = bool(BONUS.search(str(description.get('raw_value') or '')))
    audit['description_bonus_match'] = bonus
    if bonus:
        audit['reasons'].append('PRINTED_BONUS_DESCRIPTION')
    audit['eligible'] = not audit['reasons']
    return audit
