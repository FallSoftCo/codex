"""Exercise the real catalog placement path without Linux OS modules."""
import asyncio
import copy
import importlib.abc
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

class WindowsImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'fcntl','pwd','grp'}:
            raise ModuleNotFoundError('Windows does not supply '+fullname)

sys.meta_path.insert(0,WindowsImports())
from lax_connector.room_origin_control import RoomOriginControl
from lax_connector.placement_view import view

class PlacementPlatform(unittest.IsolatedAsyncioTestCase):
    def value(self, enabled=True):
        return {'schema':'hollywood-placement/v1','authorityId':'authority',
                'agentId':'agent','hostId':'host','state':'enabled' if enabled else 'paused',
                'newExecutionAdmitted':False,'drainVerified':False,'mayApply':False,
                'placement':{'authority':'authority','agent':'agent','host':'host',
                             'revision':3,'enabled':enabled}}

    async def test_catalog_edge_reads_actual_projection(self):
        for enabled in (True,False):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as tmp:
                calls=[]
                async def request(method,path):
                    calls.append((method,path))
                    return self.value(enabled)
                control=RoomOriginControl(config={'authorityId':'authority','agentId':'agent','hostId':'host'},
                    request=request,thread='original-thread',state=tmp)
                result=await control.parent_placement()
                expected={'state':'enabled','hostId':'host','revision':3,'generation':None} if enabled else None
                self.assertEqual(result,expected)
                self.assertEqual(calls,[('GET','placements/agent')])
                saved=json.loads((Path(tmp)/'parent-placement.json').read_text())
                self.assertEqual(saved['state'],'enabled' if enabled else 'paused')
                self.assertNotIn('lax_connector.host',sys.modules)
                self.assertNotIn('lax_connector.collaboration_bridge',sys.modules)

    async def test_cross_scope_or_mutation_metadata_cannot_admit(self):
        for field,value in [('authorityId','other'),('mayApply',True),('newExecutionAdmitted',True)]:
            data=self.value();data[field]=value
            with self.subTest(field=field), self.assertRaises(ValueError):
                view(data,'authority','agent','host')

if __name__=='__main__': unittest.main()
