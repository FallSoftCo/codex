import importlib.util
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

spec = importlib.util.spec_from_file_location("room_inspect", Path(__file__).parents[1] / "lax_connector/room_inspect.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class CanonicalReadHttpTest(unittest.TestCase):
    def test_reads_use_original_agent_authority_and_preserve_revision_and_cursor(self):
        seen = []
        agent = "11111111-1111-4111-8111-111111111111"
        authority = "22222222-2222-4222-8222-222222222222"
        room = "33333333-3333-4333-8333-333333333333"
        reply = {"actors": [{"id": agent, "revision": 7}], "nextAfter": agent}
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((self.command, self.path, self.headers.get("Authorization"), self.headers.get("X-Hollywood-Authority"), self.headers.get("X-Hollywood-Agent")))
                data = json.dumps(reply).encode()
                self.send_response(200); self.end_headers(); self.wfile.write(data)
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "connector.json"
                path.write_text(json.dumps({"hollywoodUrl": "http://127.0.0.1:"+str(server.server_port), "token": "synthetic-private-token", "agentId": agent, "authorityId": authority}));path.chmod(0o600)
                self.assertEqual(module.inspect_local(path,"hollywood_room_info",{"roomId":room}),reply)
                self.assertEqual(module.inspect_local(path,"hollywood_agents",{"after":agent,"limit":2}),reply)
                self.assertEqual(seen,[("GET","/hollywood/v3/rooms/"+room,"Bearer synthetic-private-token",authority,agent),("GET","/hollywood/v3/agents?limit=2&after="+agent,"Bearer synthetic-private-token",authority,agent)])
                self.assertNotIn("synthetic-private-token",json.dumps(reply))
                with self.assertRaises(ValueError): module.inspect_local(path,"hollywood_agents",{"limit":False})
                self.assertEqual(len(seen),2)
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_foreign_or_public_configuration_is_rejected_before_any_network_call(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"connector.json";path.write_text('{}');path.chmod(0o644)
            with self.assertRaises(PermissionError):module.inspect_local(path,"hollywood_rooms",{})

if __name__ == "__main__": unittest.main()
