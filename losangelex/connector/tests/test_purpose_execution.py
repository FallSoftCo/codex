"""Real file locks and detached native ownership; no model behavior claims."""
import copy,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace

from lax_connector.context_runtime import ContextAgent
from lax_connector.effects import Effects
from lax_connector.execution_lifecycle import ExecutionLifecycle
from lax_connector.tool_execution import participation
from test_completed_report_reconcile import Fixture


class PurposeExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.config={"agentId":"fixture-agent","state":str(self.root/"state"),"binary":"/unused",
            "homes":{p:str(self.root/p) for p in ("reader","writer","responder")},
            "tokens":{p:"synthetic-not-a-credential" for p in ("reader","writer","responder")}}

    def test_independent_purposes_coexist_and_exclude_duplicate_or_all_context_launch(self):
        agents=[ContextAgent(self.config,purpose=p) for p in ("reader","writer","responder")]
        for agent in agents:self.addCleanup(agent.release_locks)
        self.assertEqual([list(a.runners) for a in agents],[["reader"],["writer"],["responder"]])
        self.assertEqual(len({a.status_path for a in agents}),3)
        for purpose in ("reader","writer","responder",None):
            with self.assertRaises(BlockingIOError):ContextAgent(self.config,purpose=purpose)
        for agent in agents:agent.release_locks()
        all_contexts=ContextAgent(self.config)
        self.addCleanup(all_contexts.release_locks)
        with self.assertRaises(BlockingIOError):ContextAgent(self.config,purpose="writer")

    def test_tool_callback_remains_with_original_owner_across_scheduler_change(self):
        c=Fixture(self.root)
        original=c.captured_execution()
        params={"threadId":c.thread,"turnId":original["nativeTurn"],"callId":"original",
                "tool":"hollywood_rooms","arguments":{}}
        with c.effects.tool_scope("item/tool/call",params):
            c.active["request"]["id"]="changed"
            c.active["delivery"]["event"]="changed"
            self.assertEqual(participation(c),original)
        self.assertEqual(participation(c)["request"]["id"],"changed")

    def test_executor_transport_uses_detached_explicit_owner_without_connector(self):
        c=Fixture(self.root)
        original=c.captured_execution()
        config={**c.config,"binary":"/unused"}
        lifecycle=ExecutionLifecycle(original,config=config,transport=lambda *a:None,
                                     journal_directory=self.root/"journal")
        original["delivery"]["generation"]=99
        config["hostId"]="changed"
        self.assertEqual(lifecycle.owner["delivery"]["generation"],3)
        self.assertEqual(lifecycle.config["hostId"],c.host)
        self.assertFalse(hasattr(lifecycle,"c"))


if __name__=="__main__":unittest.main()
