"""Concurrent native callbacks cannot borrow another execution's read context."""
import asyncio
import unittest
from uuid import UUID
from lax_connector.host_capture_reads import HostCaptureReads


class HostCaptureReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_callbacks_preserve_source_and_release_context(self):
        rows = [{key: str(UUID(int=index * 10 + offset))
                 for offset, key in enumerate(('id','agent','host','delivery'), 1)}
                | {'generation': 1, 'claim_id': 'original-'+str(index)}
                for index in (1, 2)]
        by_id = {row['id']: row for row in rows}
        def transport(method, path):
            row = by_id[path.split('/')[1].split('?')[0]]
            return {'executor': row, 'capture': {
                'schema': 'hollywood-host-execution-capture/v1', 'admitsExecution': False,
                'snapshot': {'delivery': {'id': row['delivery']}},
                'role': {'principal': row['agent']}, 'work': None, 'goal': None}}
        reader = HostCaptureReads(transport)
        entered = [asyncio.Event(), asyncio.Event()]
        async def callback(index):
            row = rows[index]
            with reader.bind(row):
                entered[index].set()
                await entered[1-index].wait()
                self.assertEqual(reader.read('GET','agents/'+row['agent']+'/role'),
                                 {'principal': row['agent']})
                with self.assertRaises(PermissionError):
                    reader.read('GET','agents/'+rows[1-index]['agent']+'/role')
                with self.assertRaises(PermissionError):
                    reader.read('PUT','physical-workspaces/anything',{})
            with self.assertRaises(PermissionError):
                reader.read('GET','agents/'+row['agent']+'/role')
        await asyncio.gather(callback(0), callback(1))
        self.assertIsNone(reader.current.get())
