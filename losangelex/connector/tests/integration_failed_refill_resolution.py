"""Original pre-model failed-refill evidence and output-bearing broken controls."""
import argparse,copy,json,os
from pathlib import Path
from lax_connector.automatic_refill_failed_resolution import failure_proof
from lax_connector.automatic_refill_history import recovered_installed
p=argparse.ArgumentParser();p.add_argument("--journal",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
a.output.mkdir(mode=0o700);j=json.loads(a.journal.read_text());original=Path(j["originalHistory"]["path"]);raw=original.read_bytes();installed=recovered_installed(j["originalHistory"],j["request"]["operationId"])
proof=failure_proof(j,installed)
# Change ONLY the suffix after the verified installed checkpoint+receipt.
# Its original prefix/hash remains valid, so rejection must inspect the turn.
start=installed["nativeHistoryBytes"];boundary=raw.index(b"\n",start)+1
badrow=json.dumps({"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Broken control: model already acted"}]}}).encode()+b"\n"
fixture=a.output/"output-bearing-original.jsonl";fixture.write_bytes(raw[:boundary]+badrow+raw[boundary:])
bad=copy.deepcopy(j);st=fixture.stat();bad["originalHistory"].update(path=str(fixture),device=st.st_dev,inode=st.st_ino)
try:failure_proof(bad,installed)
except RuntimeError as e:
 assert "model output or another effect" in str(e),str(e)
else:raise AssertionError("Output-bearing failed inference was incorrectly cleared")
bad=copy.deepcopy(j);bad["request"]["phase"]="midTurn"
try:failure_proof(bad,installed)
except RuntimeError as e:assert "pre-turn" in str(e)
else:raise AssertionError("Mid-turn failure was incorrectly cleared")
assert original.read_bytes()==raw
(a.output/"QUALIFIED.json").write_text(json.dumps({"original":proof,"outputBearingAndMidTurnControlsRejected":True,"originalBytesUnchanged":True,"modelCalls":0,"effectsReplayed":0},indent=2))
print("Actual original pre-model failure verified; output-bearing/mid-turn controls rejected; original unchanged")
