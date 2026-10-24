"""Dependency approval boundaries; no live-socket/model claim from fixtures."""
import copy,unittest
from lax_connector.purpose_dependency_transition import approved
from lax_connector.collaboration_bridge import Held
class DependencyTransitionTests(unittest.TestCase):
    def fixture(self):
        before={"schema":"lax-purpose-readiness/v1","authorityId":"authority","hostId":"host",
            "configurationSha256":"own-config","workspaceIdentitySha256":"own-workspace",
            "dependencyFiles":{"own-unit":"unchanged","bridge":"old","channel":"same"},
            "bridgeRevision":1}
        current=copy.deepcopy(before);current["bridgeRevision"]=2;current["dependencyFiles"]["bridge"]="new"
        transition={"state":"accepted","schema":"lax-drained-bridge-upgrade/v1",
            "agents":["agent"],"authorityId":"authority","hostId":"host",
            "expectedBridgeRevision":1,"canonicalTransition":{"bridge":{"revision":2}},
            "configurationSha256":"new-digest","originalArtifactHashes":{"bridge":"old","channel":"same"}}
        return before,current,transition
    def test_only_reviewed_external_dependencies_change(self):
        b,c,t=self.fixture();approved(b,c,t,"agent","bridge","channel","new-digest")
        self.assertEqual(b["dependencyFiles"]["bridge"],"old")
    def test_own_files_workspace_and_approval_scope_remain_fenced(self):
        for change in ["unit","workspace","scope","pending","current","archive"]:
            with self.subTest(change=change):
                b,c,t=self.fixture()
                if change=="unit":c["dependencyFiles"]["own-unit"]="changed"
                elif change=="workspace":c["workspaceIdentitySha256"]="other"
                elif change=="scope":t["agents"]=["other-agent"]
                elif change=="pending":t["state"]="intent"
                elif change=="current":t["canonicalTransition"]["bridge"]["revision"]=3
                else:t["originalArtifactHashes"]["bridge"]="not-original"
                with self.assertRaises(Held):approved(b,c,t,"agent","bridge","channel","new-digest")
    def test_unreviewed_bridge_and_unknown_dependency_path_rejected(self):
        b,c,t=self.fixture()
        with self.assertRaises(Held):approved(b,c,t,"agent","bridge","channel","other-digest")
        c["dependencyFiles"]["new-path"]="unreviewed"
        with self.assertRaises(Held):approved(b,c,t,"agent","bridge","channel","new-digest")
if __name__=="__main__":unittest.main()
