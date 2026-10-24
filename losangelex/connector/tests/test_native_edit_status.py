"""Scoped protected receipt projection; guardian/lifecycle are explicit fixtures."""
import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from lax_connector import native_edit_status as status
from lax_connector.collaboration_bridge import Held
class ClaimReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'commands').mkdir()
        self.owner={'agentId':str(uuid4())}
        self.frame={'schema':'lax-native-edit-status/v1','after':None,'agentId':self.owner['agentId'],
            'deliveryId':str(uuid4()),'generation':1,'claimId':'context-admit:fixture',
            'contextId':str(uuid4()),'nativeThread':'fixture-thread','nativeTurn':'fixture-turn','roleRevision':1}
        def admin(method,route):
            self.assertEqual((method,route),('GET','deliveries/'+self.frame['deliveryId']))
            return {'delivery':{'state':'running','cancellation_requested':False},
                    'purposeExecutionScope':self.frame}
        self.capture=SimpleNamespace(state=self.root,admin_http=admin)
    def put(self,n,phase,state='completed',agent=None):
        claim=str(uuid4());source={k:self.frame[k] for k in ['agentId','deliveryId','generation','nativeThread','nativeTurn']}
        source.update(agentId=agent or source['agentId'],callId='fixture-call-'+str(n))
        row={'state':state,'wire':{'operationId':'fixture-operation-'+str(n),'source':source,
            'command':{'action':phase,'claimId':claim}},'status':409 if state=='rejected' else None}
        if state=='completed':row['result']={'claim':{'id':claim,'revision':2,'state':'active','target':{'privateInternalNotProjected':'fixture'}}}
        if state=='rejected':row['rejection']='Claim revision changed'
        (self.root/'commands'/(format(n,'064x')+'.json')).write_text(json.dumps(row))
        return claim
    def read(self):
        with patch.object(status,'guardian_peer',return_value=self.owner):
            return status.carry(self.capture,(123,456,456),self.frame,self.owner)['result']
    def test_claim_inspection_rejection_and_accepted_revision_are_visible_but_historical(self):
        accepted=self.put(1,'acquire');rejected=self.put(2,'inspect','rejected')
        value=self.read();rows=value['operations']
        self.assertEqual([r['claimId'] for r in rows],[accepted,rejected])
        self.assertEqual(rows[0]['claimReceipt'],{'id':accepted,'revision':2,'state':'active'})
        self.assertTrue(rows[0]['claimReceiptIsHistorical'])
        self.assertEqual(rows[1]['effectBoundary'],'metadata_request_rejected')
        self.assertTrue(rows[1]['confirmedPostRejected'])
        self.assertEqual(rows[1]['rejection'],'Claim revision changed')
        self.assertFalse(value['mayApply'])
        self.assertTrue(all(not r['automaticRetryAuthorized'] for r in rows))
    def test_pending_original_claim_is_not_accepted_or_retried_and_foreign_scope_is_hidden(self):
        self.put(1,'renew','unknown');self.put(2,'acquire',agent=str(uuid4()))
        rows=self.read()['operations'];self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['effectBoundary'],'original_effect_unsettled')
        self.assertIsNone(rows[0]['claimReceipt'])
        self.assertFalse(rows[0]['confirmedPostRejected'])
    def test_pagination_retains_claim_rows_and_original_journals(self):
        for n in range(1,19):self.put(n,'inspect','rejected')
        before={p.name:p.read_bytes() for p in (self.root/'commands').iterdir()}
        first=self.read();self.assertEqual(len(first['operations']),16)
        self.frame['after']=first['nextCursor'];second=self.read();self.assertEqual(len(second['operations']),2)
        self.assertIsNone(second['nextCursor'])
        self.assertEqual(before,{p.name:p.read_bytes() for p in (self.root/'commands').iterdir()})
    def test_scope_change_is_refused_before_reading_other_work(self):
        with patch.object(status,'guardian_peer',return_value={'agentId':str(uuid4())}):
            with self.assertRaises(Held):status.carry(self.capture,(123,456,456),self.frame,self.owner)
if __name__=='__main__':unittest.main()
