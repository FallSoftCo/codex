"""Crash/reopen and two-connection receive identity contract; no inference."""
import tempfile
import unittest
from pathlib import Path
from lax_connector.room_receive import RoomReceiveJournal, ReceiveConflict


class ReceiveRecovery(unittest.TestCase):
    def test_original_handoff_survives_reopen_without_resend(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'receive.sqlite'
            one=RoomReceiveJournal(path);two=RoomReceiveJournal(path)
            args=dict(authority='authority',agent='agent',event='event',thread='thread',seq=9,payload={'body':'original'})
            self.assertEqual(one.stage(**args)['state'],'received')
            self.assertTrue(one.begin_handoff('authority','agent','event'))
            self.assertFalse(two.begin_handoff('authority','agent','event'))
            one.close();two.close()
            restored=RoomReceiveJournal(path)
            self.assertEqual(restored.stage(**args)['state'],'handoff')
            self.assertFalse(restored.begin_handoff('authority','agent','event'))
            with self.assertRaises(ReceiveConflict):restored.stage(**{**args,'payload':{'body':'changed'}})
            # Positive RPC ACK remains pending until native durable evidence.
            restored.acknowledge('authority','agent','event',{'turn':{'id':'original-turn'}})
            self.assertEqual(restored.pending('authority','agent')[0]['state'],'acknowledged')
            self.assertFalse(restored.begin_handoff('authority','agent','event'))
            restored.close()
