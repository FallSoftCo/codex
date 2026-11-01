"""Real kernel reader/writer contention; no runtime, service or provider mocks."""
import os,sys,time,tempfile,subprocess,unittest
from pathlib import Path
from lax_connector.native_image_upgrade import registry_lock,registry_read_lock
@unittest.skipUnless(os.geteuid()==0,'Protected actual filesystem ownership required')
class RegistryReadLockTests(unittest.TestCase):
 def holder(self,root,seconds):
  code='import os,fcntl,sys,time;f=os.open(sys.argv[1],os.O_RDWR|os.O_CREAT,0o600);fcntl.flock(f,fcntl.LOCK_EX);print("held",flush=True);time.sleep(float(sys.argv[2]))'
  p=subprocess.Popen([sys.executable,'-I','-B','-c',code,str(root/'registry.lock'),str(seconds)],stdout=subprocess.PIPE,text=True)
  self.assertEqual(p.stdout.readline().strip(),'held');return p
 def test_wait_shared_readers_and_exclusive_writer_fence(self):
  with tempfile.TemporaryDirectory(dir='/var/lib') as tmp:
   root=Path(tmp)
   with self.holder(root,.2) as p:
    started=time.monotonic()
    with registry_read_lock(root,timeout=1):
     self.assertGreater(time.monotonic()-started,.1)
     with registry_read_lock(root,timeout=.2):pass
     # The short-lived flock helper has exited; its parent-held FD still fences writes.
     with self.assertRaises(BlockingIOError):
      with registry_lock(root):pass
    p.wait(timeout=1)
   with registry_lock(root):pass
 def test_writer_wait_is_bounded_and_does_not_remove_its_lock(self):
  with tempfile.TemporaryDirectory(dir='/var/lib') as tmp:
   root=Path(tmp)
   with self.holder(root,.3) as p:
    started=time.monotonic()
    with self.assertRaises(BlockingIOError):
     with registry_read_lock(root,timeout=.03):pass
    self.assertLess(time.monotonic()-started,.2)
    with self.assertRaises(BlockingIOError):
     with registry_lock(root):pass
    p.wait(timeout=1)
   with registry_lock(root):pass
