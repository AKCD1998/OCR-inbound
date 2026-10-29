"""Synthetic eligibility regressions; no invoices, answers, models or images."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'experiments'/'document_ai'))
from correction_eligibility import assess_row


class Rules:
    @staticmethod
    def _protected(row):
        return (bool(row.get('relationships')) or row.get('counted_in_receiving') is False
                or row.get('source_row_role') not in ('goods', 'goods_detail')
                or row.get('non_receipt') is True or row.get('is_return') is True
                or row.get('receiving_eligible') is False)


def diagnostic(kind='adaptive_field_conflict'):
    old, new = {'raw_value': 'SYNTHETIC_OLD'}, {'raw_value': 'SYNTHETIC_NEW'}
    if kind == 'adaptive_field_conflict':
        return {'type':kind, 'field':'lot', 'previous':old, 'candidate':new, 'source_association_approved':False}
    if kind == 'supplier_pattern_conflicting_source_field':
        return {'type':kind, 'field':'lot', 'kept':old, 'candidate':new, 'automatic_overwrite_allowed':False}
    if kind == 'adaptive_bounded_field_candidates':
        return {'type':kind, 'field':'lot', 'candidates':[old,new], 'association_verified':False}
    return {'type':'amount_unparsed_numeric_evidence', 'candidates':[new]}


def row(*relations):
    return {'source_row_role':'goods', 'section':'goods', 'counted_in_receiving':True,
            'relationships':list(relations), 'fields':{'description':{'raw_value':'Synthetic Product'}}}


class EligibilityTests(unittest.TestCase):
    def test_exact_four_historical_diagnostics_only_filter_disposable_copy(self):
        kinds = ['adaptive_field_conflict','supplier_pattern_conflicting_source_field',
                 'adaptive_bounded_field_candidates','amount_unparsed_numeric_evidence']
        value=row(*(diagnostic(kind) for kind in kinds));before=deepcopy(value)
        self.assertTrue(Rules._protected(value))
        audit=assess_row(value,Rules)
        self.assertTrue(audit['eligible']);self.assertEqual(kinds,audit['ignored_diagnostic_types'])
        self.assertFalse(audit['historical_candidate_values_used']);self.assertEqual(before,value)

    def test_mixed_free_set_and_unknown_are_still_protected(self):
        for kind in ('printed_free_or_compensation_candidate','printed_set_and_detail_same_goods_candidate',
                     'supplier_pattern_set_detail_nonadditive','unknown_future_relationship'):
            value=row(diagnostic(),{'type':kind});before=deepcopy(value)
            with self.subTest(kind=kind):
                audit=assess_row(value,Rules)
                self.assertFalse(audit['eligible']);self.assertIn(kind,audit['blocked_relationship_types'])
                self.assertEqual(before,value)

    def test_exact_schema_no_discriminator_alias_extra_flags_or_nested_row_payload(self):
        for mode in ('alias','case','extra_flag','nested_row','nested_raw','nan_raw','bool_raw','approved','unknown_field','unhashable_field','string_false','missing_key'):
            relation=diagnostic()
            if mode=='alias':relation['kind']=relation.pop('type')
            elif mode=='case':relation['type']='ADAPTIVE_FIELD_CONFLICT'
            elif mode=='extra_flag':relation['is_bonus']=True
            elif mode=='nested_row':relation['candidate']['relationships']=[{'type':'printed_free_or_compensation_candidate'}]
            elif mode=='nested_raw':relation['candidate']['raw_value']={'is_bonus':True}
            elif mode=='nan_raw':relation['candidate']['raw_value']=float('nan')
            elif mode=='bool_raw':relation['candidate']['raw_value']=True
            elif mode=='approved':relation['source_association_approved']=True
            elif mode=='unknown_field':relation['field']='is_bonus'
            elif mode=='unhashable_field':relation['field']=['lot']
            elif mode=='string_false':relation['source_association_approved']='false'
            else:relation.pop('candidate')
            with self.subTest(mode=mode):self.assertFalse(assess_row(row(relation),Rules)['eligible'])

    def test_original_semantic_flags_survive_diagnostic_filter(self):
        for key,value in [('source_row_role','set_parent'),('counted_in_receiving',False),
                          ('non_receipt',True),('is_return',True),('receiving_eligible',False)]:
            item=row(diagnostic());item[key]=value
            with self.subTest(key=key):self.assertFalse(assess_row(item,Rules)['eligible'])

    def test_printed_bonus_description_shared_by_bridge_and_guard(self):
        for description in ('Synthetic free goods','Synthetic FOC','ของแถม Synthetic','สินค้าแถม Synthetic'):
            item=row(diagnostic());item['fields']['description']['raw_value']=description
            with self.subTest(description=description):
                self.assertFalse(assess_row(item,Rules)['eligible'])
                self.assertTrue(assess_row(item,Rules)['description_bonus_match'])

    def test_malformed_relations_abstain_and_unrelated_row_metadata_conserved(self):
        for relations in ({},'adaptive_field_conflict',[None],[{}]):
            value=row();value['relationships']=relations;value['unknown_metadata']={'do_not_drop':[1,2]}
            before=deepcopy(value)
            with self.subTest(relations=relations):
                self.assertFalse(assess_row(value,Rules)['eligible']);self.assertEqual(before,value)

    def test_historical_values_do_not_become_proposed_answers_or_change_eligibility(self):
        item=row(diagnostic());other=deepcopy(item)
        other['relationships'][0]['candidate']['raw_value']='TOTALLY DIFFERENT UNTRUSTED VALUE'
        self.assertEqual(assess_row(item,Rules),assess_row(other,Rules))


if __name__=='__main__':unittest.main()
