"""Real filesystem metadata/content checks; no synthetic service or model."""
import os,tempfile,unittest
from pathlib import Path
from lax_connector.native_release import closure
from lax_connector.native_release_transition import _closure_identity

@unittest.skipUnless(os.geteuid()==0,'protected release owner required')
class LinkMetadataTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='lax-release-links-',dir='/var/lib');self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name)/'release';self.root.mkdir();self.path=self.root/'binary'
  self.path.write_bytes(b'original payload');self.path.chmod(0o755)
  self.plan={'closure':closure(self.root)};self.link=Path(self.tmp.name)/'staging-link'
 def test_hard_link_metadata_change_requires_original_bytes(self):
  os.link(self.path,self.link);_closure_identity(self.plan)
  self.link.unlink();_closure_identity(self.plan)
 def test_same_size_changed_bytes_with_restored_mtime_are_rejected(self):
  before=self.path.stat();self.path.write_bytes(b'modified payload')
  os.utime(self.path,ns=(before.st_atime_ns,before.st_mtime_ns))
  with self.assertRaises(ValueError):_closure_identity(self.plan)
 def test_same_content_different_inode_is_rejected(self):
  other=self.root/'other';other.write_bytes(self.path.read_bytes());other.chmod(0o755)
  before=self.path.stat();os.utime(other,ns=(before.st_atime_ns,before.st_mtime_ns));other.replace(self.path)
  with self.assertRaises(ValueError):_closure_identity(self.plan)
 def test_permissions_and_entry_changes_are_rejected(self):
  self.path.chmod(0o700)
  with self.assertRaises(ValueError):_closure_identity(self.plan)
