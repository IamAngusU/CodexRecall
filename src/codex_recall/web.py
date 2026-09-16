from __future__ import annotations


PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>CodexRecall</title>
  <style>
    :root{font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;color:#202124;background:#f5f6f7;line-height:1.45}
    *{box-sizing:border-box}button,input,select{font:inherit}button{cursor:pointer}
    body{margin:0;min-height:100vh}#app{display:grid;grid-template-columns:320px 1fr;min-height:100vh}
    aside{border-right:1px solid #d8dadd;background:#fff;display:flex;flex-direction:column;min-height:100vh;position:sticky;top:0;height:100vh}
    .brand{padding:20px 18px 12px;font-weight:750;font-size:20px}.muted{color:#6d7178}.tiny{font-size:12px}
    .searchbox{padding:0 14px 12px}.searchbox input,.toolbar input,.toolbar select{width:100%;border:1px solid #c9ccd1;border-radius:7px;padding:8px 10px;background:transparent}
    #threads{overflow:auto;padding:0 8px 16px}.thread{display:block;width:100%;text-align:left;border:0;background:transparent;border-radius:7px;padding:10px;margin:1px 0;color:inherit}
    .thread:hover,.thread.active{background:#edf0f3}.thread strong{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.thread span{display:block;margin-top:3px}
    main{min-width:0}.top{position:sticky;top:0;z-index:5;background:rgba(245,246,247,.96);backdrop-filter:blur(8px);border-bottom:1px solid #d8dadd;padding:14px 22px}
    .title{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.toolbar{display:grid;grid-template-columns:minmax(180px,1fr) 110px auto auto auto;gap:8px;margin-top:10px;align-items:center}
    button{border:1px solid #c6c9ce;border-radius:7px;background:#fff;color:#222;padding:7px 10px}button:hover{background:#eef1f4}.primary{background:#202124;color:#fff;border-color:#202124}.primary:hover{background:#34363a}
    #content{max-width:1100px;margin:0 auto;padding:22px}.empty{padding:50px 20px;text-align:center;color:#6d7178}
    .turn{margin:0 0 22px}.turn-head{border:1px solid #d7dade;border-radius:9px 9px 0 0;background:#fff;padding:9px 12px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
    .turn-head .tldr{font-weight:600;flex:1;min-width:220px}.metric{font-size:12px;color:#60656d;background:#f0f2f4;border-radius:99px;padding:3px 8px}
    .item{background:#fff;border:1px solid #d7dade;border-top:0;padding:12px 14px}.item:last-child{border-radius:0 0 9px 9px}.item.hidden-item{opacity:.55}
    .item-head{display:flex;align-items:center;gap:8px;margin-bottom:8px}.label{font-weight:750;font-size:12px;letter-spacing:.04em}.phase{font-size:11px;color:#6d7178}.actions{margin-left:auto;display:flex;gap:5px}.actions button{padding:3px 7px;font-size:12px}
    .text{white-space:pre-wrap;overflow-wrap:anywhere}.user{border-left:4px solid #3f6fdb}.assistant{border-left:4px solid #2f8b57}.work{border-left:4px solid #92979f;background:#fafafa}
    details summary{cursor:pointer;font-weight:600}.work .text{margin-top:10px;font:12px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace;max-height:520px;overflow:auto;background:#f4f5f6;padding:10px;border-radius:6px}
    .files{width:100%;margin-top:8px;border-collapse:collapse;font-size:12px}.files td{border-top:1px solid #e2e4e7;padding:4px 6px}.files td:first-child{max-width:650px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    #searchResults{display:none;background:#fff;border:1px solid #d7dade;border-radius:9px;margin-bottom:18px}.result{padding:11px 13px;border-top:1px solid #e1e3e6}.result:first-child{border-top:0}.result mark{background:#ffef9c}.result-title{font-weight:650}.result-text{margin-top:5px;white-space:pre-wrap}.result-actions{margin-top:7px;display:flex;gap:6px}
    #toast{position:fixed;right:18px;bottom:18px;background:#202124;color:white;padding:9px 13px;border-radius:7px;display:none;z-index:20}
    @media(max-width:820px){#app{grid-template-columns:1fr}aside{display:none}.toolbar{grid-template-columns:1fr 95px auto}.optional{display:none}#content{padding:12px}.top{padding:12px}}
    @media(prefers-color-scheme:dark){:root{color:#e8eaed;background:#161719}aside,.top,.turn-head,.item,#searchResults{background:#202124;border-color:#3a3d42}.thread:hover,.thread.active{background:#303236}.muted,.tiny,.phase,.metric{color:#aeb3bb}.metric,.work .text{background:#292b2f}.work{background:#1d1e20}button{background:#292b2f;color:#e8eaed;border-color:#484b51}button:hover{background:#36393e}.primary{background:#e8eaed;color:#202124}.toolbar input,.toolbar select,.searchbox input{border-color:#4a4d52;color:inherit}.files td,.result{border-color:#36393e}}
  </style>
</head>
<body>
<div id="app">
  <aside>
    <div class="brand">CodexRecall <span class="tiny muted" id="stats"></span></div>
    <div class="searchbox"><input id="threadQuery" placeholder="Find a task…" autocomplete="off"></div>
    <div id="threads"></div>
  </aside>
  <main>
    <div class="top">
      <div class="title" id="title">Loading local conversations…</div>
      <div class="tiny muted" id="subtitle"></div>
      <div class="toolbar">
        <input id="messageQuery" placeholder="Search every message and tool result…" autocomplete="off">
        <select id="latest" title="Items shown"><option>25</option><option>50</option><option selected>100</option><option>250</option><option>500</option><option>1000</option></select>
        <label class="tiny optional"><input type="checkbox" id="work" checked> work</label>
        <label class="tiny optional"><input type="checkbox" id="hidden"> hidden</label>
        <button id="reindex">Refresh</button>
      </div>
    </div>
    <div id="content">
      <div id="searchResults"></div>
      <div id="timeline" class="empty">Building the local index…</div>
    </div>
  </main>
</div>
<div id="toast"></div>
<script>
const TOKEN="__TOKEN__";
const INITIAL_THREAD="__THREAD__";
const state={thread:null,threads:[],items:[],summaries:{},queryTimer:null};
const $=id=>document.getElementById(id);
const esc=value=>String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
async function api(path,options={}){options.headers={...(options.headers||{}),"X-CodexRecall-Token":TOKEN};if(options.body){options.headers["Content-Type"]="application/json"}const response=await fetch(path,options);if(!response.ok){throw new Error((await response.text())||response.statusText)}return response.json()}
function toast(text){const node=$("toast");node.textContent=text;node.style.display="block";clearTimeout(node.timer);node.timer=setTimeout(()=>node.style.display="none",2200)}
function when(ms){if(!ms)return "";const date=new Date(ms);return date.toLocaleString()}
function label(item){const names={userMessage:"YOU",agentMessage:"CODEX",reasoning:"WORK SUMMARY",commandExecution:"COMMAND",fileChange:"FILES",mcpToolCall:"MCP",webSearch:"WEB",contextCompaction:"COMPACTION"};return names[item.item_type]||item.item_type.toUpperCase()}
function isWork(item){return !["userMessage","agentMessage"].includes(item.item_type)}
async function copy(text){await navigator.clipboard.writeText(text);toast("Copied")}
async function copyExact(item){const data=await api(`/api/exact?thread_id=${encodeURIComponent(item.thread_id)}&item_id=${encodeURIComponent(item.item_id)}`);await copy(data.text)}
async function copyRecovery(item){const data=await api(`/api/recovery?thread_id=${encodeURIComponent(item.thread_id)}&item_id=${encodeURIComponent(item.item_id)}&before=4&after=4&include_work=1`);await copy(data.text)}
async function hideItem(item,hidden){await api("/api/hide",{method:"POST",body:JSON.stringify({thread_id:item.thread_id,item_id:item.item_id,hidden})});await loadThread(state.thread)}
function itemNode(item){const article=document.createElement("article");article.className=`item ${item.role==="user"?"user":item.role==="assistant"?"assistant":"work"}${item.hidden?" hidden-item":""}`;const head=document.createElement("div");head.className="item-head";head.innerHTML=`<span class="label">${esc(label(item))}</span><span class="phase">${esc(item.phase||"")} ${esc(when(item.created_at_ms))}</span><span class="actions"></span>`;const actions=head.querySelector(".actions");const exact=document.createElement("button");exact.textContent="Copy exact";exact.onclick=()=>copyExact(item);actions.appendChild(exact);const recover=document.createElement("button");recover.textContent="Recover";recover.onclick=()=>copyRecovery(item);actions.appendChild(recover);const hiding=document.createElement("button");hiding.textContent=item.hidden?"Show":"Hide";hiding.onclick=()=>hideItem(item,!item.hidden);actions.appendChild(hiding);article.appendChild(head);if(isWork(item)){const details=document.createElement("details");const summary=document.createElement("summary");summary.textContent=`${label(item)} · ${item.text.length.toLocaleString()} indexed chars`;details.appendChild(summary);const text=document.createElement("div");text.className="text";text.textContent=item.text;details.appendChild(text);article.appendChild(details)}else{const text=document.createElement("div");text.className="text";text.textContent=item.text;article.appendChild(text)}return article}
function summaryHead(turnId,summary){const head=document.createElement("div");head.className="turn-head";const counts=summary?.counts||{};const work=(counts.commandExecution||0)+(counts.mcpToolCall||0)+(counts.webSearch||0);head.innerHTML=`<span class="tldr">${esc(summary?.tldr||"Turn work")}</span><span class="metric">${work} tools</span><span class="metric">${summary?.file_count||0} files</span><span class="metric">+${summary?.additions||0} / −${summary?.deletions||0}</span>`;if(summary?.files?.length){const table=document.createElement("table");table.className="files";summary.files.slice(0,30).forEach(file=>{const row=document.createElement("tr");row.innerHTML=`<td title="${esc(file.path)}">${esc(file.path)}</td><td>+${file.additions}</td><td>−${file.deletions}</td>`;table.appendChild(row)});head.appendChild(table)}return head}
function renderTimeline(){const target=$("timeline");target.className="";target.innerHTML="";if(!state.items.length){target.className="empty";target.textContent="No matching items.";return}let current=null,section=null;for(const item of state.items){const turn=item.turn_id||"unassigned";if(turn!==current){current=turn;section=document.createElement("section");section.className="turn";section.appendChild(summaryHead(turn,state.summaries[turn]));target.appendChild(section)}section.appendChild(itemNode(item))}}
function renderThreads(){const target=$("threads");target.innerHTML="";for(const thread of state.threads){const button=document.createElement("button");button.className=`thread${state.thread===thread.id?" active":""}`;button.innerHTML=`<strong>${esc(thread.display_name)}</strong><span class="tiny muted">${esc(when(thread.updated_at_ms))} · ${thread.item_count} items</span>`;button.onclick=()=>loadThread(thread.id);target.appendChild(button)}}
async function loadThreads(query=""){const data=await api(`/api/threads?q=${encodeURIComponent(query)}&limit=200`);state.threads=data.threads;renderThreads();if(!state.thread&&state.threads.length){await loadThread(INITIAL_THREAD||state.threads[0].id)}}
async function loadThread(id){if(!id)return;state.thread=id;renderThreads();const latest=parseInt($("latest").value,10);const work=$("work").checked?1:0;const hidden=$("hidden").checked?1:0;const data=await api(`/api/thread/${encodeURIComponent(id)}?limit=${latest}&include_work=${work}&include_hidden=${hidden}`);state.items=data.items;state.summaries=data.summaries||{};$("title").textContent=data.thread.display_name;$("subtitle").textContent=`${data.thread.id} · ${data.thread.cwd||"no workspace"} · ${data.thread.model||"unknown model"}`;renderTimeline();await api("/api/preferences",{method:"POST",body:JSON.stringify({thread_id:id,latest_count:latest,include_work:!!work})})}
async function searchMessages(query){const box=$("searchResults");if(!query.trim()){box.style.display="none";box.innerHTML="";return}const data=await api(`/api/search?q=${encodeURIComponent(query)}&limit=60`);box.innerHTML="";box.style.display="block";for(const item of data.results){const result=document.createElement("div");result.className="result";result.innerHTML=`<div class="result-title">${esc(item.display_name)} · ${esc(label(item))}</div><div class="result-text">${esc(item.snippet)}</div><div class="result-actions"></div>`;const actions=result.querySelector(".result-actions");const exact=document.createElement("button");exact.textContent="Copy exact";exact.onclick=()=>copy(item.text);actions.appendChild(exact);const recover=document.createElement("button");recover.textContent="Recover context";recover.onclick=()=>copyRecovery(item);actions.appendChild(recover);const open=document.createElement("button");open.textContent="Open task";open.onclick=()=>loadThread(item.thread_id);actions.appendChild(open);box.appendChild(result)}}
$("threadQuery").addEventListener("input",event=>{clearTimeout(state.queryTimer);state.queryTimer=setTimeout(()=>loadThreads(event.target.value),180)});
$("messageQuery").addEventListener("input",event=>{clearTimeout(state.queryTimer);state.queryTimer=setTimeout(()=>searchMessages(event.target.value),180)});
for(const id of ["latest","work","hidden"]){$(id).addEventListener("change",()=>loadThread(state.thread))}
$("reindex").onclick=async()=>{toast("Refreshing index…");const data=await api("/api/reindex",{method:"POST",body:"{}"});toast(`Updated ${data.result.items_written} items in ${data.result.elapsed_ms} ms`);await loadThreads($("threadQuery").value);await loadThread(state.thread)};
(async()=>{try{const status=await api("/api/status");$("stats").textContent=`${status.stats.threads} / ${status.stats.items}`;await loadThreads()}catch(error){$("timeline").textContent=error.message}})();
  </script>
</body>
</html>"""
