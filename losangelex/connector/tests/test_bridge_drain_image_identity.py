"""Real filesystem controls for protected offline image aliases; no model claim."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from lax_connector.collaboration_upgrade import same_installed_image

@unittest.skipUnless(sys.platform.startswith("linux") and os.geteuid()==0,
                     "Linux installation observer uses administrator-protected paths")
class InstalledImageTests(unittest.TestCase):
    def root(self):
        return tempfile.TemporaryDirectory(prefix="bridge-image-",dir="/var/lib")

    def image(self,root,name):
        p=Path(root)/name;p.write_bytes(b"native-image");p.chmod(0o755);return p

    def test_protected_hardlink_and_symlink_aliases_name_same_image(self):
        with self.root() as root:
            a=self.image(root,"approved");b=Path(root)/"hardlink";os.link(a,b)
            c=Path(root)/"protected-link";c.symlink_to(a)
            self.assertTrue(same_installed_image(str(b),str(a)))
            self.assertTrue(same_installed_image(str(c),str(a)))

    def test_equal_content_in_different_inode_is_rejected(self):
        with self.root() as root:
            a=self.image(root,"approved");b=self.image(root,"copy")
            c=Path(root)/"link-to-copy";c.symlink_to(b)
            self.assertFalse(same_installed_image(str(b),str(a)))
            self.assertFalse(same_installed_image(str(c),str(a)))

    def test_untrusted_link_writable_missing_relative_and_chained_aliases_rejected(self):
        with self.root() as root:
            a=self.image(root,"approved");b=Path(root)/"untrusted-link";b.symlink_to(a);os.lchown(b,1000,1000)
            self.assertFalse(same_installed_image(str(b),str(a)))
            b.unlink();b=self.image(root,"writable");b.chmod(0o777)
            self.assertFalse(same_installed_image(str(b),str(a)))
            c=Path(root)/"link";c.symlink_to(a);d=Path(root)/"chain";d.symlink_to(c)
            self.assertFalse(same_installed_image(str(d),str(a)))
            self.assertFalse(same_installed_image(str(Path(root)/"missing"),str(a)))
            self.assertFalse(same_installed_image("relative",str(a)))

if __name__=="__main__":unittest.main()
