import importlib.util,marshal,os,tempfile,unittest
from pathlib import Path
from lax_connector.native_release import closure
from lax_connector.native_release_transition import _closure_identity
@unittest.skipUnless(os.geteuid()==0,'Actual protected release ownership required')
class DerivedCacheTest(unittest.TestCase):
 def test_only_sealed_source_bytecode_is_accepted(self):
  with tempfile.TemporaryDirectory(dir='/var/lib') as tmp:
   root=Path(tmp);source=root/'module.py';source.write_text('value=42\n');cache=root/'__pycache__';cache.mkdir();plan={'closure':closure(root)}
   p=cache/('module.'+__import__('sys').implementation.cache_tag+'.pyc');p.write_bytes(importlib.util.MAGIC_NUMBER+b'\0'*12+marshal.dumps(compile(source.read_bytes(),str(source),'exec',dont_inherit=True)))
   _closure_identity(plan)
   p.write_bytes(importlib.util.MAGIC_NUMBER+b'\0'*12+marshal.dumps(compile('value=99',str(source),'exec',dont_inherit=True)))
   with self.assertRaisesRegex(ValueError,'differs from original'):_closure_identity(plan)
 def test_arbitrary_additions_and_missing_source_are_rejected(self):
  with tempfile.TemporaryDirectory(dir='/var/lib') as tmp:
   root=Path(tmp);source=root/'module.py';source.write_text('value=42\n');plan={'closure':closure(root)};(root/'unknown.py').write_text('value=0\n')
   with self.assertRaises(ValueError):_closure_identity(plan)
   (root/'unknown.py').unlink();source.unlink()
   with self.assertRaises(ValueError):_closure_identity(plan)
if __name__=='__main__':unittest.main()
