"""Disposable release metadata boundaries; canonical/systemd/probe facts synthetic."""

import copy
import hashlib
import json
import os
import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lax_connector import native_image_upgrade as image, native_release as release
from lax_connector import native_release_transition as transition, service_memory
from lax_connector import service_observer as observer
import test_native_image_upgrade as fixtures


@unittest.skipUnless(os.geteuid() == 0, "root-protected metadata fixtures required")
class ReleaseTests(unittest.TestCase):
    get = fixtures.ImageTransitionTests.get

    def setUp(self):
        fixtures.ImageTransitionTests.setUp(self)
        # Synthetic units must never reload the real host service manager.
        self.reload = self.enterContext(patch.object(transition.subprocess, "run"))
        for p in (self.home / "work", self.home / "codex-home"):
            p.mkdir()
        self.python = self.package / "venv/bin/python"
        self.python.parent.mkdir(parents=True)
        self.python.write_bytes(b"unexecuted old interpreter")
        self.python.chmod(0o755)
        self.new_root = self.root / "release-new"
        shutil.copytree(self.package, self.new_root / "native")
        self.new_binary = self.new_root / "native/bin/codex"
        self.new_python = self.new_root / "native/venv/bin/python"
        self.config.update(workspace=str(self.home / "work"),
                           codexHome=str(self.home / "codex-home"),
                           model="unchanged-model", modelReasoningEffort="unchanged-effort",
                           sandbox="danger-full-access")
        fixtures.write(self.home / "connector.json", self.config)
        self.unit = self.root / "fixture.service"
        self.unit.write_text(
            "[Service]\nUser=fixture\nWorkingDirectory=" + str(self.home / "work") +
            "\nExecStart=" + str(self.python) + " -m lax_connector.connector --config " +
            str(self.home / "connector.json") +
            " --serve\nKillMode=control-group\nNoNewPrivileges=no\nMemoryMax=2G\n")
        self.unit.chmod(0o644)
        self.info["FragmentPath"] = str(self.unit)
        self.old.update(binaryDevice=self.binary.stat().st_dev,
                        binaryInode=self.binary.stat().st_ino,
                        unitDefinitionDigest=hashlib.sha256(self.unit.read_bytes()).hexdigest())
        fixtures.write(self.registry / "enrollment.json", self.old)
        self.old_digest = observer.digest(self.old)
        self.spec = {"hostId": self.host, "binary": str(self.binary),
                     "interpreter": str(self.python), "model": "unchanged-model"}
        self.enterContext(patch.object(service_memory, "approved_spec",
                                      return_value=(self.spec, {"original": True}, False)))
        self.enterContext(patch.object(release.pwd, "getpwuid",
                                      return_value=SimpleNamespace(pw_dir=str(self.home), pw_name="fixture")))
        observer.unit_definition.side_effect = lambda info: hashlib.sha256(self.unit.read_bytes()).hexdigest()
        self.enterContext(patch.object(release, "probe", side_effect=self.probe_release))
        self.request_spec = {
            "expectedEnrollment": self.old_digest,
            "expectedConfigurationSha256": hashlib.sha256((self.home / "connector.json").read_bytes()).hexdigest(),
            "expectedDefinition": self.old["unitDefinitionDigest"],
            "oldReleaseRoot": str(self.package), "newReleaseRoot": str(self.new_root),
            "oldBinary": str(self.binary), "newBinary": str(self.new_binary),
            "oldInterpreter": str(self.python), "newInterpreter": str(self.new_python),
        }
        self.originals = {"config": (self.home / "connector.json").read_bytes(),
                          "unit": self.unit.read_bytes(),
                          "oldManifest": (self.registry / "old.json").read_bytes()}
        self.prepared = self.root / "prepared"

    def probe_release(self, binary, interpreter, uid, home, root):
        binary = Path(binary)
        package = binary.parent.parent
        assets = {}
        for label, relative in {"entrypoint": "bin/codex", "codeModeHost": "bin/codex-code-mode-host",
                                "bubblewrap": "codex-resources/bwrap", "ripgrep": "codex-path/rg"}.items():
            p = package / relative
            st = p.stat()
            assets[label] = {"path": str(p), "device": st.st_dev, "inode": st.st_ino,
                             "size": st.st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        return {"nativePackage": {"packageRoot": str(package), "assets": assets,
                                  "metadataSha256": hashlib.sha256((package / "codex-package.json").read_bytes()).hexdigest()},
                "connector": {"uid": uid, "module": str(Path(root) / "connector.py"),
                              "prefix": str(Path(root) / "venv")}, "modelsStarted": 0}

    def prepare(self):
        self.review = release.prepare(self.authority, self.host, self.agent,
                                      self.request_spec, self.prepared)
        return self.review

    def configure_instruction_adoption(self):
        from lax_connector.room_participation import VERSION, instructions_digest
        self.config.update(runtimeMode='room-conversation', nativeThreadId='original-fixture-thread',
            authorityId=self.authority, conversationResumeInstructions={
                'baseInstructions': 'Original approved role', 'developerInstructions': 'Retain original restriction'})
        manifest = self.root / 'fixture-host.json'
        fixtures.write(manifest, {'schema': 'lax-native-host/v1', 'runtimeMode': 'room-conversation',
            'authorityId': self.authority, 'hostId': self.host, 'ownerAgentId': self.agent,
            'binary': str(self.binary), 'codexHome': str(self.home / 'codex-home'),
            'state': str(self.home / 'state/native'), 'socket': str(self.root / 'unopened-fixture.socket')})
        self.config['nativeServer'] = {'manifest': str(manifest)}
        fixtures.write(self.home / 'connector.json', self.config)
        self.request_spec.update(newBinary=str(self.binary), retainNativeImage=True,
            expectedConfigurationSha256=hashlib.sha256((self.home / 'connector.json').read_bytes()).hexdigest(),
            newConversationInstructionAdoption={'policy': VERSION,
                'expectedResumeInstructionsSha256': instructions_digest(self.config['conversationResumeInstructions'])})
        checksum = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        self.enterContext(patch('lax_connector.native_dependency.capture', return_value={'imageSha256': checksum}))
        self.enterContext(patch('lax_connector.native_dependency.pin_package', side_effect=lambda value, package: value))
        self.enterContext(patch('lax_connector.native_dependency.verify'))
        self.enterContext(patch.object(release, 'transport_inspect', return_value={
            'nativeThreadId': self.config['nativeThreadId'], 'status': 'idle', 'modelCalls': 0}))
        self.enterContext(patch('lax_connector.host.request', return_value={'enabled': False, 'busy': None, 'pending': None}))

    def test_instruction_adoption_is_derived_and_pinned_in_actual_release_targets(self):
        import base64
        self.configure_instruction_adoption()
        original = (self.home / 'connector.json').read_bytes()
        review = self.prepare()
        self.assertEqual((self.home / 'connector.json').read_bytes(), original)
        plan = json.loads((self.prepared / 'release-plan.json').read_text())
        after = json.loads(base64.b64decode(plan['targets'][0]['after']))
        fields = {'conversationParticipationPolicy', 'conversationInstructionAdoptionId', 'conversationResumeInstructions'}
        self.assertEqual({k: v for k, v in after.items() if k not in fields},
                         {k: v for k, v in self.config.items() if k not in fields})
        self.assertEqual(after['conversationResumeInstructions']['developerInstructions'], 'Retain original restriction')
        self.assertEqual(review['instructionAdoption'], plan['instructionAdoption'])
        self.assertEqual(after['conversationInstructionAdoptionId'], plan['instructionAdoption']['adoptionId'])
        self.reload.assert_not_called()
        accepted = self.approve()
        self.assertEqual(accepted['state'], 'accepted')
        self.assertEqual(json.loads((self.home / 'connector.json').read_text()), after)

    def test_instruction_review_cas_failure_has_no_definition_or_config_effect(self):
        self.configure_instruction_adoption()
        original = (self.home / 'connector.json').read_bytes()
        self.request_spec['newConversationInstructionAdoption']['expectedResumeInstructionsSha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'instruction CAS changed'):
            self.prepare()
        self.assertEqual((self.home / 'connector.json').read_bytes(), original)
        self.assertFalse(self.prepared.exists())
        self.reload.assert_not_called()

    def approve(self):
        return transition.approve(self.authority, self.host, self.agent, self.prepared,
                                  self.review["preparationDigest"])

    def inspect(self):
        return transition.status(self.authority, self.host, self.agent)

    def recover(self):
        value = self.inspect()
        return transition.reconcile(self.authority, self.host, self.agent,
                                    value["operationId"], value["intentDigest"])

    def test_review_is_metadata_only_and_only_two_software_fields_change(self):
        result = self.prepare()
        self.assertEqual((self.home / "connector.json").read_bytes(), self.originals["config"])
        self.assertEqual(self.unit.read_bytes(), self.originals["unit"])
        plan = json.loads((self.prepared / "release-plan.json").read_text())
        import base64
        after = json.loads(base64.b64decode(plan["targets"][0]["after"]))
        self.assertEqual(after, {**self.config, "binary": str(self.new_binary)})
        after_unit = base64.b64decode(plan["targets"][1]["after"])
        self.assertEqual(after_unit, self.originals["unit"].replace(
            str(self.python).encode(), str(self.new_python).encode()))
        self.assertEqual(result["modelsStarted"], 0)

    def test_failed_manager_reload_retains_original_intent_for_reconciliation(self):
        self.prepare()
        self.reload.side_effect = transition.subprocess.CalledProcessError(
            1, ["systemctl", "daemon-reload"]
        )
        with self.assertRaises(transition.subprocess.CalledProcessError):
            self.approve()
        current = self.inspect()
        self.assertEqual(current["metadataStages"], [1, 1, 1])
        self.assertEqual(current["state"], "pending")
        self.assertFalse(current["acceptedRecord"])
        self.reload.assert_called_once_with(
            ["systemctl", "daemon-reload"], check=True, capture_output=True
        )
        self.reload.side_effect = None
        self.info["NeedDaemonReload"] = "yes"
        with self.assertRaisesRegex(ValueError, "not loaded by systemd"):
            self.recover()
        self.info["NeedDaemonReload"] = "no"
        accepted = self.recover()
        self.assertEqual(accepted["operationId"], current["operationId"])
        self.assertEqual(accepted["state"], "accepted")

    def test_execstart_text_inside_comments_is_preserved(self):
        import base64
        comment = ("# retain ExecStart=" + str(self.python) +
                   " -m lax_connector.connector --config " +
                   str(self.home / "connector.json") + " --serve\n").encode()
        self.unit.write_bytes(self.unit.read_bytes() + comment)
        self.old["unitDefinitionDigest"] = hashlib.sha256(self.unit.read_bytes()).hexdigest()
        fixtures.write(self.registry / "enrollment.json", self.old)
        self.request_spec.update(expectedEnrollment=observer.digest(self.old),
                                 expectedDefinition=self.old["unitDefinitionDigest"])
        self.prepare()
        plan = json.loads((self.prepared / "release-plan.json").read_text())
        self.assertTrue(base64.b64decode(plan["targets"][1]["after"]).endswith(comment))

    def test_full_transition_preserves_identity_state_history_and_restart_pins(self):
        self.prepare()
        restart = self.registry / "restart-approval.json"
        fixtures.write(restart, {"original": "explicit renewal required"})
        restart_bytes = restart.read_bytes()
        state_before = {p.name: p.read_bytes() for p in self.state.iterdir()}
        result = self.approve()
        self.assertEqual(result["state"], "accepted")
        software = release.active_spec(self.spec, self.authority, self.host, self.agent)
        self.assertEqual(software, {**self.spec, "binary": str(self.new_binary),
                                   "interpreter": str(self.new_python)})
        self.assertEqual(self.spec["binary"], str(self.binary))
        self.assertEqual(self.originals["oldManifest"], (self.registry / "old.json").read_bytes())
        self.assertEqual(restart_bytes, restart.read_bytes())
        self.assertEqual(state_before, {p.name: p.read_bytes() for p in self.state.iterdir()})
        self.assertTrue(all(m == "GET" for m, _ in self.calls))
        with image.registry_lock(self.registry) as fd:
            image.require_settled_transition(fd)
        self.assertEqual(self.recover(), result)

    def test_live_guardian_admission_or_unknown_executor_prevents_intent(self):
        self.prepare()
        for fault in ("guardian", "enabled", "executor"):
            with self.subTest(fault=fault):
                self.info["ActiveState"] = "active" if fault == "guardian" else "inactive"
                self.info["MainPID"] = "100" if fault == "guardian" else "0"
                self.pending["enabled"] = fault == "enabled"
                self.executors["executors"] = [{"agent": self.agent, "state": "unknown"}] if fault == "executor" else []
                with self.assertRaises(ValueError):
                    self.approve()
                self.assertFalse(list(self.registry.glob("image-*-intent.json")))

    def test_old_guardian_descendant_or_nss_change_blocks(self):
        self.prepare()
        self.process.return_value = {"pid": 901, "start": "old"}
        with self.assertRaises(ValueError):
            self.approve()
        self.process.return_value = None
        self.members.return_value = {987}
        with self.assertRaises(ValueError):
            self.approve()
        self.members.return_value = set()
        with patch.object(release.pwd, "getpwuid", return_value=SimpleNamespace(pw_dir="/different")):
            with self.assertRaises(ValueError):
                self.approve()

    def test_wrong_original_cas_and_same_release_path_refused(self):
        for key in ("expectedEnrollment", "expectedConfigurationSha256", "expectedDefinition"):
            before = self.request_spec[key]
            self.request_spec[key] = "0"*64
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.prepare()
            self.request_spec[key] = before
        self.request_spec["newReleaseRoot"] = self.request_spec["oldReleaseRoot"]
        self.request_spec["newBinary"] = self.request_spec["oldBinary"]
        self.request_spec["newInterpreter"] = self.request_spec["oldInterpreter"]
        with self.assertRaises(ValueError):
            self.prepare()

    def test_preparation_digest_tamper_and_config_cas_refused(self):
        self.prepare()
        with self.assertRaises(ValueError):
            transition.approve(self.authority, self.host, self.agent, self.prepared, "0"*64)
        (self.home / "connector.json").write_bytes(b'{"changed":true}')
        with self.assertRaises(ValueError):
            self.approve()
        self.assertFalse(list(self.registry.glob("image-*-intent.json")))

    def interrupt(self, boundary):
        original = image._write
        def write(fd, name, value, **kwargs):
            if boundary(fd, name, value):
                raise RuntimeError("synthetic metadata interruption")
            return original(fd, name, value, **kwargs)
        with patch.object(image, "_write", side_effect=write):
            with self.assertRaises(RuntimeError):
                self.approve()

    def test_intent_before_pointer_is_explicitly_reconciled_without_replaying_commands(self):
        self.prepare()
        self.interrupt(lambda fd, name, v: name == image.INDEX and v["state"] == "intent")
        before = self.inspect()
        self.assertEqual(before["metadataStages"], [0, 0, 0])
        with image.registry_lock(self.registry) as fd:
            with self.assertRaises(ValueError):
                image.require_settled_transition(fd)
        self.assertEqual(self.recover()["state"], "accepted")

    def test_config_unit_prefix_can_finish_only_recorded_enrollment(self):
        self.prepare()
        self.interrupt(lambda fd, name, v: name == "enrollment.json")
        value = self.inspect()
        self.assertEqual(value["metadataStages"], [1, 1, 0])
        intent_path = self.registry / ("image-" + value["operationId"] + "-intent.json")
        original_intent = intent_path.read_bytes()
        self.assertEqual(self.recover()["state"], "accepted")
        self.assertEqual(intent_path.read_bytes(), original_intent)

    def test_accepted_record_before_index_and_current_pointer_can_finish(self):
        self.prepare()
        self.interrupt(lambda fd, name, v: name == image.INDEX and v["state"] == "accepted")
        self.assertEqual(self.inspect()["state"], "pending")
        self.assertEqual(self.recover()["state"], "accepted")

    def test_index_before_software_pointer_is_held_from_registration_until_reconciled(self):
        self.prepare()
        self.interrupt(lambda fd, name, v: name == release.CURRENT)
        with image.registry_lock(self.registry) as fd:
            with self.assertRaises((ValueError, FileNotFoundError)):
                image.require_settled_transition(fd)
        self.assertEqual(self.recover()["state"], "accepted")

    def test_uncertain_bytes_or_nonprefix_metadata_are_never_repaired(self):
        self.prepare()
        self.interrupt(lambda fd, name, v: name == "enrollment.json")
        (self.home / "connector.json").write_bytes(self.originals["config"])
        self.assertEqual(self.inspect()["state"], "held")
        before = self.unit.read_bytes()
        with self.assertRaises(ValueError):
            self.recover()
        self.assertEqual(self.unit.read_bytes(), before)

    def test_helper_change_during_pending_intent_is_held_and_not_reapproved(self):
        self.prepare()
        self.interrupt(lambda fd, name, v: name == "enrollment.json")
        helper = self.new_root / "native/codex-path/rg"
        helper.write_bytes(b"changed")
        self.assertEqual(self.inspect()["state"], "held")
        with self.assertRaises(ValueError):
            self.recover()

    def test_writable_entry_or_external_directory_link_is_not_a_closure(self):
        self.new_python.chmod(0o777)
        with self.assertRaises(PermissionError):
            self.prepare()
        self.new_python.chmod(0o755)
        (self.new_root / "escape").symlink_to("/usr/lib", target_is_directory=True)
        with self.assertRaises(ValueError):
            self.prepare()

    def test_inverse_is_a_new_reviewed_drained_transition(self):
        self.prepare()
        first = self.approve()
        enrolled = json.loads((self.registry / "enrollment.json").read_text())
        self.request_spec.update(
            expectedEnrollment=observer.digest(enrolled),
            expectedConfigurationSha256=hashlib.sha256((self.home / "connector.json").read_bytes()).hexdigest(),
            expectedDefinition=hashlib.sha256(self.unit.read_bytes()).hexdigest(),
            oldReleaseRoot=str(self.new_root), newReleaseRoot=str(self.package),
            oldBinary=str(self.new_binary), newBinary=str(self.binary),
            oldInterpreter=str(self.new_python), newInterpreter=str(self.python))
        self.prepared = self.root / "inverse-prepared"
        self.prepare()
        second = self.approve()
        self.assertNotEqual(first["operationId"], second["operationId"])
        self.assertEqual(self.originals["unit"], self.unit.read_bytes())
        self.assertEqual(release.active_spec(self.spec, self.authority, self.host, self.agent), self.spec)

    def test_repeated_upgrades_reference_history_without_recursive_growth(self):
        roots = [(self.package, self.binary, self.python),
                 (self.new_root, self.new_binary, self.new_python)]
        sizes = []
        prior = None
        for step in range(4):
            old, new = roots[step % 2], roots[(step + 1) % 2]
            enrollment = json.loads((self.registry / "enrollment.json").read_text())
            self.request_spec.update(
                expectedEnrollment=observer.digest(enrollment),
                expectedConfigurationSha256=hashlib.sha256(
                    (self.home / "connector.json").read_bytes()).hexdigest(),
                expectedDefinition=hashlib.sha256(self.unit.read_bytes()).hexdigest(),
                oldReleaseRoot=str(old[0]), newReleaseRoot=str(new[0]),
                oldBinary=str(old[1]), newBinary=str(new[1]),
                oldInterpreter=str(old[2]), newInterpreter=str(new[2]))
            self.prepared = self.root / ("prepared-repeat-" + str(step))
            self.prepare()
            accepted = self.approve()
            record = json.loads((self.registry / release.CURRENT).read_text())
            self.assertEqual(record["priorIndex"], transition.prior_reference(prior))
            if prior is not None:
                self.assertEqual(record["priorIndex"]["digest"], observer.digest(prior))
                self.assertNotIn("closure", record["priorIndex"])
            sizes.append(len(json.dumps(record)))
            self.assertEqual(accepted["state"], "accepted")
            prior = record
        self.assertLess(max(sizes) - min(sizes), 1024)

    def test_restrictive_umask_does_not_change_original_config_or_unit_modes(self):
        self.prepare()
        before = [(self.home / "connector.json").stat().st_mode & 0o777,
                  self.unit.stat().st_mode & 0o777]
        original_umask = os.umask(0o077)
        try:
            self.approve()
        finally:
            os.umask(original_umask)
        self.assertEqual(before, [(self.home / "connector.json").stat().st_mode & 0o777,
                                  self.unit.stat().st_mode & 0o777])

    def test_changed_helper_after_acceptance_is_not_new_readiness(self):
        self.prepare()
        self.approve()
        (self.new_root / "native/codex-path/rg").write_bytes(b"changed")
        self.assertEqual(self.inspect()["state"], "held")
        with image.registry_lock(self.registry) as fd:
            with self.assertRaises(ValueError):
                image.require_settled_transition(fd)

    def test_wrong_intent_digest_or_new_unstopped_executor_cannot_reconcile(self):
        self.prepare()
        self.interrupt(lambda fd, name, v: name == "enrollment.json")
        value = self.inspect()
        with self.assertRaises(ValueError):
            transition.reconcile(self.authority, self.host, self.agent,
                                 value["operationId"], "0"*64)
        self.executors["executors"] = [{"agent": self.agent, "state": "unknown"}]
        with self.assertRaises(ValueError):
            self.recover()
        self.assertEqual(self.inspect()["metadataStages"], [1, 1, 0])

    def test_legacy_intent_before_index_is_reported_held_without_replay(self):
        original = image._write
        self.definition = observer.unit_definition(self.info)
        def interrupted(fd, name, value, **kwargs):
            if name == image.INDEX:
                raise RuntimeError("legacy pointer not published")
            return original(fd, name, value, **kwargs)
        with patch.object(image, "_write", side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                fixtures.ImageTransitionTests.approve(self)
        self.assertFalse((self.registry / image.INDEX).exists())
        value = self.inspect()
        self.assertEqual(value["state"], "held")
        self.assertTrue(value["operations"][0]["intentDigest"])

    def test_lost_accepted_release_index_never_grants_registration(self):
        self.prepare()
        self.approve()
        (self.registry / image.INDEX).unlink()
        with image.registry_lock(self.registry) as fd:
            with self.assertRaisesRegex(ValueError, "index is missing"):
                image.require_settled_transition(fd)
        self.assertEqual(self.inspect()["state"], "held")

    def test_legacy_same_path_api_and_receipt_remain_compatible(self):
        self.definition = observer.unit_definition(self.info)
        result = fixtures.ImageTransitionTests.approve(self)
        self.assertEqual(result["schema"], "lax-native-image-upgrade/v1")
        self.assertEqual(result["state"], "accepted")
        self.assertFalse((self.registry / release.CURRENT).exists())

    def test_local_route_review_uses_original_agent_and_preserves_other_configuration(self):
        import base64
        import threading
        from http.server import HTTPServer, BaseHTTPRequestHandler
        seen=[]
        authority,agent=self.authority,self.agent
        class Handler(BaseHTTPRequestHandler):
            def do_GET(inner):
                seen.append((inner.path,dict(inner.headers)))
                body=json.dumps({'authorityId':authority,'rooms':[]}).encode()
                inner.send_response(200);inner.send_header('Content-Length',str(len(body)))
                inner.end_headers();inner.wfile.write(body)
            def log_message(*args):pass
        server=HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            self.config.update(hollywoodUrl='https://original.invalid',token='synthetic-route-only')
            fixtures.write(self.home/'connector.json',self.config)
            before=(self.home/'connector.json').read_bytes()
            self.request_spec['expectedConfigurationSha256']=hashlib.sha256(before).hexdigest()
            new_url='http://127.0.0.1:'+str(server.server_port)
            self.request_spec.update(expectedHollywoodUrl=self.config['hollywoodUrl'],newHollywoodUrl=new_url)
            self.prepare()
            plan=json.loads((self.prepared/'release-plan.json').read_text())
            after=json.loads(base64.b64decode(plan['targets'][0]['after']))
            self.assertEqual(after,{**self.config,'binary':str(self.new_binary),'hollywoodUrl':new_url,'federationAuthorityId':authority})
            self.assertEqual((self.home/'connector.json').read_bytes(),before)
            self.assertEqual(plan['newHollywoodUrl'],new_url)
            self.assertEqual(len(seen),1)
            self.assertEqual(seen[0][0],'/hollywood/v3/rooms')
            self.assertEqual(seen[0][1]['X-Hollywood-Authority'],authority)
            self.assertEqual(seen[0][1]['X-Hollywood-Agent'],agent)
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)

    def test_route_review_cannot_send_original_credential_to_external_host(self):
        self.config.update(hollywoodUrl='https://original.invalid',token='synthetic-route-only')
        fixtures.write(self.home/'connector.json',self.config)
        before=(self.home/'connector.json').read_bytes()
        self.request_spec['expectedConfigurationSha256']=hashlib.sha256(before).hexdigest()
        self.request_spec.update(expectedHollywoodUrl=self.config['hollywoodUrl'],
            newHollywoodUrl='http://external.invalid:19431')
        with self.assertRaisesRegex(ValueError,'host-local Hollywood route'):
            self.prepare()
        self.assertEqual((self.home/'connector.json').read_bytes(),before)


    def test_paired_native_metadata_retains_exact_interrupted_prefix(self):
        import base64
        self.prepare()
        path=self.prepared/'release-plan.json'
        plan=json.loads(path.read_text())
        extras=[]
        for name in ('native-manifest.json','native-host.service'):
            target=self.root/name;target.write_bytes(b'original native declaration')
            target.chmod(0o600)
            extras.append({'path':str(target),'uid':0,'mode':0o600,
                'before':base64.b64encode(target.read_bytes()).decode(),
                'after':base64.b64encode(b'new pinned native declaration').decode()})
        plan['sharedNativeUpgrade']={'unit':'synthetic-native-host.service','targets':extras}
        fixtures.write(path,plan)
        self.review['preparationDigest']=observer.digest(plan)
        original=transition._write_target
        def interrupted(target):
            original(target)
            if target['path']==extras[0]['path']:
                raise OSError('retained interruption after native manifest publication')
        from lax_connector import shared_native_release
        with patch.object(shared_native_release,'offline') as offline:
            with patch.object(transition,'_write_target',side_effect=interrupted):
                with self.assertRaisesRegex(OSError,'retained interruption'):
                    self.approve()
            status=self.inspect()
            self.assertEqual(status['state'],'pending')
            self.assertEqual(status['metadataStages'],[1,1,1,0,0])
            recovered=self.recover()
            self.assertEqual(recovered['state'],'accepted')
            self.assertEqual(recovered['metadataStages'],[1,1,1,1,1])
            self.assertEqual(self.inspect()['operationId'],status['operationId'])
            # Existing deployed readers do not know this additive extension.
            # They must still recognize the accepted original 2-target receipt.
            legacy={k:v for k,v in plan.items() if k!='sharedNativeUpgrade'}
            with image.registry_lock(self.registry) as fd:
                self.assertEqual(transition.states(legacy,fd),[1,1,1])
            self.assertTrue(offline.called)
        for target in extras:
            self.assertEqual(Path(target['path']).read_bytes(),b'new pinned native declaration')


class ReleaseCommandTests(unittest.TestCase):
    def test_exact_cli_prepare_approve_status_and_reconcile_routes(self):
        import contextlib
        import io
        from lax_connector import service_admin
        base = ["lax-service", "--authority", str(fixtures.UUID(int=1)),
                "--host", str(fixtures.UUID(int=2)), "--agent", str(fixtures.UUID(int=3))]
        routes = [
            (["--prepare-release", "/review/spec.json", "--output", "/review/new"],
             release, "prepare"),
            (["--approve-release", "/review/new", "--expected-preparation-sha256", "a"*64],
             transition, "approve"),
            (["--release-status", "--operation-id", "b"*64], transition, "status"),
            (["--reconcile-release", "b"*64, "--expected-intent-sha256", "c"*64],
             transition, "reconcile"),
        ]
        for arguments, module, name in routes:
            with self.subTest(name=name), patch("sys.argv", base + arguments), \
                    patch.object(observer, "protected", return_value={"review": "only"}), \
                    patch.object(module, name, return_value={"ok": True}) as action, \
                    contextlib.redirect_stdout(io.StringIO()):
                service_admin.main()
                action.assert_called_once()


@unittest.skipUnless(os.geteuid() == 0 and os.environ.get("LAX_RELEASE_PROBE_UID"),
                     "explicit real service-UID fixture route required")
class RealIdentityProbeTests(unittest.TestCase):
    def test_actual_uid_layout_and_helper_access_without_native_or_provider_calls(self):
        import platform
        import subprocess
        import sys
        import tempfile
        uid = int(os.environ["LAX_RELEASE_PROBE_UID"])
        import pwd
        user = pwd.getpwuid(uid).pw_name
        with tempfile.TemporaryDirectory(prefix="lax-release-real-uid-", dir="/dev/shm") as directory:
            root = Path(directory)
            root.chmod(0o755)
            code = Path(release.__file__).with_name("native_package.py").read_bytes()
            script = root / "probe.py"
            script.write_bytes(code)
            script.chmod(0o644)
            for relative in ("bin/codex", "bin/codex-code-mode-host", "codex-resources/bwrap", "codex-path/rg"):
                path = root / relative
                path.parent.mkdir(exist_ok=True)
                path.parent.chmod(0o755)
                path.write_text("#!/bin/sh\nprintf 'synthetic startup boundary\\n'\n")
                path.chmod(0o755)
            metadata = {"layoutVersion": 1, "variant": "codex", "entrypoint": "bin/codex",
                        "resourcesDir": "codex-resources", "pathDir": "codex-path",
                        "version": "0.0.1-fixture", "target": platform.machine() + "-unknown-linux-gnu"}
            (root / "codex-package.json").write_text(json.dumps(metadata))
            (root / "codex-package.json").chmod(0o644)
            cmd = ["runuser", "-u", user, "--", sys._base_executable, "-I", "-B", str(script),
                   "--binary", str(root / "bin/codex"), "--expected-uid", str(uid)]
            result = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            value = json.loads(result.stdout)
            self.assertEqual(value["uid"], uid)
            self.assertEqual(len(value["startupChecks"]), 4)
            (root / "codex-path/rg").chmod(0o700)
            denied = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
            self.assertEqual(denied.returncode, 2)
            self.assertFalse(json.loads(denied.stdout)["ready"])
