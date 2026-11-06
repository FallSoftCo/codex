"""Lead/worker tools; role is pinned to canonical Hollywood project metadata."""
from .room_tools import definition, STRING

PROJECT_TOOLS=[
 definition('lead_work','Read durable original human work and selected assignments. With workId retrieve its exact original human input; after pages outstanding work. Set a real dependency, pause, cancellation or completion explicitly; an ended turn is not work completion. For useful local work, checkpoint its material milestone with a stable key and actual versioned evidence before ending the turn. This records your assertion, not independent qualification. Repeated tool calls, waiting and paraphrases are not progress.',
   {'workId':STRING,'after':{'type':'integer','minimum':0},'state':{'type':'string','enum':['ready','waiting','paused','cancelled','complete']},'reason':STRING,'checkpoint':{'type':'object','properties':{'key':STRING,'summary':STRING,'evidence':{'type':'array','items':STRING,'minItems':1,'maxItems':8}},'required':['key','summary','evidence'],'additionalProperties':False}},[]),
 definition('lead_assign','Assign one compact, actionable task to a selected room agent. You are its lead, not a relay of human quotations. Include expected result and only necessary constraints; link larger evidence. Accepted means queued, never running/done.',
   {'workId':STRING,'agentId':STRING,'taskKey':{'type':'string','pattern':'^[a-zA-Z0-9_-]{1,80}$'},'brief':STRING,'evidence':{'type':'array','items':STRING,'maxItems':8}},['workId','agentId','taskKey','brief']),
 definition('lead_reply','Reply to the original human work, retaining its audience even when this native turn came from a worker result. Use meaningful progress, a genuine user question or completion; do not relay internal chatter.',
   {'workId':STRING,'body':STRING,'disposition':{'type':'string','enum':['progress','needs_input','complete']}},['workId','body','disposition']),
 definition('team_report','Send a concise result to the original assigning lead. Include outcome, useful facts and bounded evidence references; raw native transcripts stay private. Do not post acceptance or repeated unchanged blocks.',
   {'taskId':STRING,'outcome':{'type':'string','enum':['done','progress','blocked','waiting','failed','cancelled']},'summary':STRING,'evidence':{'type':'array','items':STRING,'maxItems':8}},['taskId','outcome','summary']),
]
PROJECT_TOOLS += [definition('lead_attention','Inspect an addressed native technical question and answer it in your real lead identity. Human permission approvals remain human-only; never impersonate the user.',{'attentionId':STRING,'response':{'type':'object','additionalProperties':True}},['attentionId'])]
PROJECT_TOOLS += [definition('lead_task','Read one original assignment and its latest concise result from the durable project ledger. Use task IDs from lead_work; full transcripts are not copied into project context.',{'taskId':STRING},['taskId'])]
PROJECT_TOOLS += [
 definition('team_question','Ask one selected peer a concise scoped question. This assigns no new execution responsibility. Keep one semantic questionKey for retries; do not poll or repeat unchanged questions. The answer resumes only its original outstanding question.',{'taskId':STRING,'workId':STRING,'recipientId':STRING,'questionKey':STRING,'question':STRING},['taskId','recipientId','questionKey','question']),
 definition('team_answer','Answer an actual addressed peer question in your own identity, briefly. Preserve the original questionEventId; an answer is not another request.',{'questionEventId':STRING,'summary':STRING},['questionEventId','summary'])]
NAMES={t['name'] for t in PROJECT_TOOLS}
