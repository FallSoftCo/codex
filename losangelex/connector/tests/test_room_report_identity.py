import unittest
from uuid import uuid4
from lax_connector.room_initial_report import report_id


class ReportIdentityTests(unittest.TestCase):
    def test_production_native_admin_shape_and_stable_distinct_successors(self):
        operation='native-admin:'+str(uuid4());sha='b2d67e6372f9dfb8135f45bd7c6b42b2a69b2a54c6509b5995da6f504c5199f4'
        legacy=operation+':initial-config:'+sha+':report'
        self.assertEqual(len(legacy),136);bounded=report_id(legacy)
        self.assertEqual(len(bounded),79);self.assertEqual(bounded,report_id(legacy))
        self.assertNotEqual(bounded,report_id(legacy.replace(sha,'0'*64)))
        self.assertNotEqual(bounded,report_id(legacy.replace(operation,'native-admin:'+str(uuid4()))))

    def test_valid_original_ids_preserved_not_normalized_or_rekeyed(self):
        for original in ('x','x'*128,'native-admin:'+str(uuid4())+':report'):
            self.assertEqual(report_id(original),original)
        self.assertLessEqual(len(report_id('x'*129)),128)
        for invalid in (None,'',[],123):
            with self.assertRaises(ValueError):report_id(invalid)
