// @exec: {"max_output_tokens": 15000}
text(await tools.context_read({}));
text(await tools.context_material_read({reference:"role"}));
let r=JSON.parse(await tools.context_material_read({reference:"6b972a75-c21a-5cd6-9296-31d0e1ec457e"}));let s=r.content;while(r.nextOffset!==null){r=JSON.parse(await tools.context_material_read({reference:r.reference,revision:r.revision,offset:r.nextOffset}));s+=r.content;}store("currentWork",JSON.parse(s));text(s);
