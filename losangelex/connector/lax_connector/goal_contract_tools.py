"""Native tools for reviewed Goal definitions and durable strategy revisions."""
from uuid import UUID

NAMES={"hollywood_goal_define","hollywood_goal_adopt","hollywood_goal_plan"}

def definitions(spec):
    text={"type":"string"};rev={"type":"integer","minimum":1}
    criterion={"type":"object","additionalProperties":False,"properties":{
        "id":text,"requirement":text,"method":{"type":"string","enum":["command","artifact","review"]},
        "verification":text},"required":["id","requirement","method","verification"]}
    definition={"type":"object","additionalProperties":False,"properties":{
        "objective":text,"criteria":{"type":"array","items":criterion,"minItems":1,"maxItems":32},
        "assumptions":{"type":"array","items":text,"maxItems":16},
        "openQuestions":{"type":"array","items":text,"maxItems":16}},
        "required":["objective","criteria","assumptions","openQuestions"]}
    common={"goalId":text,"revision":rev,"sourceEventId":text,"note":text}
    alternative={"type":"object","additionalProperties":False,"properties":{
        "id":text,"approach":text,"tradeoffs":text},"required":["id","approach","tradeoffs"]}
    strategy={"type":"object","additionalProperties":False,"properties":{
        "alternatives":{"type":"array","items":alternative,"minItems":1,"maxItems":8},
        "selected":text,"rationale":text,"frontierWorkIds":{"type":"array","items":text,"maxItems":32},
        "replanWhen":{"type":"array","items":text,"maxItems":16}},
        "required":["alternatives","selected","rationale","frontierWorkIds","replanWhen"]}
    return [
      spec("hollywood_goal_define",
        "Develop or revise a Goal definition with concrete acceptance criteria and appropriate verification methods. Record assumptions and unresolved questions; discuss ambiguity with the relevant human through Hollywood. Artifact formats remain task-appropriate. Read current Goal first. definitionRevision is the latest proposed revision (0 initially). This proposes intent; it does not adopt, assign work or prove completion. sourceEventId must be readable room-visible Goal-local intent, such as the Goal source.",
        {**common,"definitionRevision":{"type":"integer","minimum":0},"definition":definition},
        [*common,"definitionRevision","definition"]),
      spec("hollywood_goal_adopt",
        "Accountable Goal manager: adopt the exact latest definition revision/digest after resolving its recorded questions. This records YOUR attributable review, never invents human approval. Read current Goal and any required real human answer first. Adoption fences older acceptance; existing unfinished effects require explicit reconciliation. No model/task starts.",
        {**common,"definitionRevision":rev,"definitionSha256":text},
        [*common,"definitionRevision","definitionSha256"]),
      spec("hollywood_goal_plan",
        "Record a durable strategy against the adopted Goal definition: alternatives considered, selected approach and rationale, current frontier of existing Work IDs and conditions for replanning. One alternative is sufficient when warranted; do not invent ceremony. Existing Work owns task dependencies and execution. Read current Goal/Work first; this records no execution. Change the plan as evidence warrants while preserving the adopted outcome.",
        {**common,"planRevision":{"type":"integer","minimum":0},"definitionRevision":rev,"strategy":strategy},
        [*common,"planRevision","definitionRevision","strategy"])
    ]

async def execute(c,name,args,operation):
    action={"hollywood_goal_define":"definition","hollywood_goal_adopt":"adopt","hollywood_goal_plan":"strategy"}[name]
    goal=str(UUID(args["goalId"]))
    payload={key:value for key,value in args.items() if key!="goalId"}
    payload["operationId"]=operation
    return await c.http("POST","goals/"+goal+"/contract/"+action,payload)
