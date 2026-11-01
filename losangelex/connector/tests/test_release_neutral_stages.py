"""Unchanged release targets neither establish nor break an applied prefix."""
import base64,hashlib,unittest
from unittest.mock import patch
from lax_connector import native_release_transition as t
class NeutralStages(unittest.TestCase):
 def test_unchanged_target_during_forward_recovery(self):
  enc=lambda b:base64.b64encode(b).decode()
  plan={'targets':[{'path':'config','uid':1,'before':enc(b'same'),'after':enc(b'same')},{'path':'unit','uid':1,'before':enc(b'old'),'after':enc(b'new')}],'priorEnrollment':{'v':1},'approvedEnrollment':{'v':2}}
  for unit,enrollment,expected in [(b'old',{'v':1},[0,0,0]),(b'new',{'v':1},[1,1,0]),(b'new',{'v':2},[1,1,1])]:
   with patch.object(t,'file_hash',side_effect=lambda p,u:(hashlib.sha256(b'same' if str(p)=='config' else unit).hexdigest(),None)),patch.object(t.image,'_json',return_value=enrollment):self.assertEqual(t.states(plan,0),expected)
  with patch.object(t,'file_hash',side_effect=lambda p,u:(hashlib.sha256(b'same' if str(p)=='config' else b'old').hexdigest(),None)),patch.object(t.image,'_json',return_value={'v':2}):
   with self.assertRaisesRegex(ValueError,'established prefix'):t.states(plan,0)
