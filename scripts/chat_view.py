"""Show every model request of an extraction trace as a small chat, in one HTML page.

usage: python scripts/chat_view.py TRACE OUT.html [--kind K ...] [--field F ...]
                                   [--owner N ...] [--value V ...]
                                   [--contains TEXT ...] [--limit N]

TRACE is a *.jsonl or *.jsonl.gz file; one still being written is read up to
where it ends. Each request shows its instruction (folded), its message with
the numbered lines, the addresses its answer names highlighted, the answer,
and what became of it (taken, asked again with reasons, no answer,
unreadable). The chain of one value (find, readings, follow-ups, list
entries) is a second view.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from docpipe.extraction import trace  # noqa: E402

NOTES = ("parameter", "coordinate", "owner", "value")
CHAINED = ("coord", "search", "check", "follow")


def _text(content) -> str:
    if content is None:
        return ""
    if not isinstance(content, list):
        return str(content)
    parts = []
    for p in content:
        if isinstance(p, dict) and p.get("type") == "text":
            parts.append(str(p.get("text", "")))
        else:
            parts.append("[image]")
    return "\n".join(parts)


def _json(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _entries(user) -> dict:
    """{number: label} of the "N label (means: ...)" lines of a request's list."""
    out = {}
    for line in (user or {}).get("list") or ():
        m = re.match(r"\s*(\d+)\s+(.*?)(?:\s*\(means:.*)?\s*$", str(line), re.S)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _spell(answer, user) -> list:
    """The entries an answer names, each written out as "N = label"."""
    if not isinstance(answer, dict) or "entry" not in answer:
        return []
    labels = _entries(user)
    picked = answer["entry"]
    picked = picked if isinstance(picked, list) else [picked]
    return [f"{n} = {labels[str(n)]}" if str(n) in labels else str(n)
            for n in picked]


def _words(answer) -> set:
    """The words an answer reads, from "words" or each of its "found"/"more"."""
    out = set()
    if isinstance(answer, dict):
        for item in [answer] + list(answer.get("found") or ()) + list(
                answer.get("more") or ()):
            if isinstance(item, dict) and item.get("words") not in (None, ""):
                out.add(str(item["words"]))
    return out


def _reasons(user) -> str:
    what = (user or {}).get("what")
    if isinstance(what, (dict, str)):
        what = [what]
    parts = []
    for w in what or ():
        if isinstance(w, dict):
            parts.append(str(w.get("why") or w.get("reason")
                             or json.dumps(w, ensure_ascii=False)))
        else:
            parts.append(str(w))
    return ", ".join(parts)


def requests_of(events: list) -> list:
    """One dict per `*_ask` event, in trace order."""
    pieces = trace.pieces_of(events)
    out = []
    for i, e in enumerate(events):
        t = str(e.get("t", ""))
        if not t.endswith("_ask"):
            continue
        sent = trace.sent(e, pieces) or {}
        msgs = [[m.get("role"), _text(m.get("content"))]
                for m in sent.get("messages") or ()]
        system = next((m[1] for m in msgs if m[0] == "system"), "")
        rest = [m for m in msgs if m[0] != "system"]
        user_text = rest[0][1] if rest and rest[0][0] == "user" else ""
        user = _json(user_text)
        user = user if isinstance(user, dict) else None
        output = e.get("output") if isinstance(e.get("output"), dict) else {}
        content = output.get("content")
        answer_text = content if isinstance(content, str) and content.strip() else None
        answer = _json(answer_text) if answer_text else None
        value = (user or {}).get("value")
        req = {k: v for k, v in e.items() if k not in ("input", "output", "t", "kind")}
        if "kind" in e:
            req["note_kind"] = e["kind"]  # the passage's or list's kind
        req.update({
            "kind": t[:-4], "system": system, "messages": rest,
            "user": user_text, "answer": answer_text,
            "answer_json": answer if isinstance(answer, (dict, list)) else None,
            "finish": output.get("finish"), "error": output.get("error"),
            "spelled": _spell(answer, user),
            "at": value.get("at") if isinstance(value, dict) else None,
            "check": "", "_event": i, "_user": user,
        })
        out.append(req)
    _check(out, events)
    for r in out:
        r.pop("_event")
        r.pop("_user")
    return out


def _same_notes(a, b) -> bool:
    return a.get("doc") == b.get("doc") and all(a.get(k) == b.get(k) for k in NOTES)


def _check(reqs: list, events: list) -> None:
    """What became of each request: taken, asked again, no answer, unreadable."""
    for pos, r in enumerate(reqs):
        if r["answer"] is None:
            r["check"] = "no answer"
            continue
        nxt = next((x for x in events[r["_event"] + 1:]
                    if x.get("t") != trace.PIECE), None)
        if (nxt and nxt.get("t") == "error" and nxt.get("kind") == "unreadable"
                and nxt.get("where") == r["kind"]):
            r["check"] = f"unreadable: {nxt.get('cause')}"
            continue
        follow = next((x for x in reqs[pos + 1:] if x["kind"] == "follow"
                       and x.get("asked") == r["kind"] and _same_notes(x, r)), None)
        if follow is None:
            r["check"] = "taken"
        else:
            why = _reasons(follow["_user"])
            r["check"] = "asked again" + (f": {why}" if why else "")


def chain_of(requests: list, index: int) -> list:
    """Indexes of the requests of one value: the find of its parameter and
    passage, the readings and follow-ups, and the list entries asked for its words."""
    r = requests[index]
    kind = r.get("asked") if r["kind"] == "follow" else r["kind"]
    if kind not in CHAINED:
        return [index]
    doc, par, own = r.get("doc"), r.get("parameter"), r.get("owner")
    members = [i for i, x in enumerate(requests)
               if x.get("doc") == doc and x.get("parameter") == par
               and x.get("owner") == own and x.get("value") == r.get("value")
               and (x["kind"] in ("coord", "search", "check")
                    or (x["kind"] == "follow" and x.get("asked") in CHAINED))]
    first = min(members + [index])
    finds = [i for i, x in enumerate(requests)
             if x["kind"] == "find" and x.get("doc") == doc
             and x.get("parameter") == par and x.get("owner") == own and i < first]
    words = set()
    for i in members:
        words |= _words(requests[i]["answer_json"])
    lists = []
    for i, x in enumerate(requests):
        if x["kind"] not in ("list", "names") or x.get("doc") != doc:
            continue
        if x.get("parameter") not in (None, par):
            continue
        u = _json(x["user"]) or {}
        if str(u.get("words", u.get("name"))) in words:
            lists.append(i)
    return sorted(set(finds[-1:] + members + lists))


def _keep(r: dict, a) -> bool:
    kinds = {k[:-4] if k.endswith("_ask") else k for k in a.kind or ()}
    if kinds and r["kind"] not in kinds:
        return False
    if a.field and r.get("parameter") not in a.field:
        return False
    if a.owner and str(r.get("owner")) not in {str(o) for o in a.owner}:
        return False
    if a.value and str(r.get("value")) not in {str(v) for v in a.value}:
        return False
    blob = "\n".join([r["system"], r["user"], r["answer"] or ""]).casefold()
    return all(s.casefold() in blob for s in a.contains or ())


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Request chats</title><style>
:root{--bg:#f6f6f4;--panel:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#ddd;--sys:#eef0f3;--user:#e8f0fb;--bot:#e6f4ea;--hit:#ffe58a;--bad:#fff1df}
@media (prefers-color-scheme: dark){:root{--bg:#161616;--panel:#1f1f1f;--ink:#e8e8e6;--muted:#9a9a94;--line:#333;--sys:#262a30;--user:#1c2a3d;--bot:#1d3325;--hit:#6b5a10;--bad:#3a2c18}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,sans-serif;display:flex;height:100vh}
#list{width:360px;min-width:240px;overflow:auto;border-right:1px solid var(--line);background:var(--panel)}
#filters{padding:8px;display:grid;grid-template-columns:1fr 1fr;gap:6px;position:sticky;top:0;background:var(--panel)}
#filters input,#filters select{width:100%;padding:5px;border:1px solid var(--line);background:var(--bg);color:var(--ink)}
#filters #q{grid-column:1/3}
.item{padding:8px 12px;border-bottom:1px solid var(--line);cursor:pointer}
.item:hover,.item.on{background:var(--user)}
.item small{color:var(--muted);display:block}
#chat{flex:1;overflow:auto;padding:16px 24px;min-width:0}
.msg{max-width:980px;margin:0 0 12px;padding:10px 14px;border-radius:10px;white-space:pre-wrap;word-break:break-word;font:12.5px ui-monospace,Consolas,monospace}
.system{background:var(--sys)} .user{background:var(--user)} .assistant{background:var(--bot);margin-left:40px} .check{background:var(--bad)}
.role{font:600 11px system-ui;color:var(--muted);text-transform:uppercase;margin-bottom:4px}
.ln{display:block} .ln.hit{background:var(--hit)} .key{color:var(--muted)}
button{padding:4px 10px;margin:0 6px 8px 0;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:6px;cursor:pointer}
@media (max-width:700px){body{flex-direction:column}#list{width:auto;height:38vh}#chat{padding:12px 16px}.assistant{margin-left:12px}}
</style></head><body>
<div id="list"><div id="filters">
<select id="fk"><option value="">kind</option></select><select id="ff"><option value="">field</option></select>
<input id="fo" placeholder="passage"><input id="fv" placeholder="value">
<input id="q" placeholder="text"></div><div id="items"></div></div>
<div id="chat"><p>Pick a request on the left.</p></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const R=JSON.parse(document.getElementById('data').textContent);
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
let cur=-1,view=null;
function fill(sel,vals){[...new Set(vals.filter(v=>v!==undefined&&v!==null&&v!==''))].sort().forEach(v=>{const o=document.createElement('option');o.value=o.textContent=v;sel.appendChild(o)})}
fill($('fk'),R.map(r=>r.kind));fill($('ff'),R.map(r=>r.parameter));
function addrs(a){const out=[];const add=x=>{if(x===undefined||x===null)return;x=String(x);
 const m=x.match(/^([A-Za-z]*)(\\d+)(?:\\.\\d+)?(?:-([A-Za-z]*)(\\d+)(?:\\.\\d+)?)?$/);if(!m)return;
 const lo=+m[2],hi=m[4]?+m[4]:lo;for(let n=lo;n<=Math.min(hi,lo+500);n++)out.push(m[1]+n)};
 const walk=o=>{if(Array.isArray(o))o.forEach(walk);else if(o&&typeof o=='object'){if('at' in o)add(o.at);Object.values(o).forEach(v=>{if(typeof v=='object')walk(v)})}};
 walk(a);return new Set(out)}
function lineKey(s){const m=String(s).match(/^\\s*([A-Za-z]*\\d+)\\b/);return m?m[1]:null}
function val(v,hit,ind){const pad='  '.repeat(ind);
 if(Array.isArray(v)){if(v.length&&v.every(x=>typeof x=='string'))return v.map(s=>{const k=lineKey(s);return '<span class="ln'+(k&&hit.has(k)?' hit':'')+'">'+esc(s)+'</span>'}).join('');
  return v.map(x=>val(x,hit,ind)).join('')}
 if(v&&typeof v=='object')return Object.entries(v).map(([k,x])=>{
  const sub=x&&typeof x=='object';return '<span class="ln"><span class="key">'+pad+esc(k)+':</span>'+(sub?'':' '+esc(x))+'</span>'+(sub?val(x,hit,ind+1):'')}).join('');
 return '<span class="ln">'+pad+esc(v)+'</span>'}
function userHtml(r,hit){try{const o=JSON.parse(r.user);if(o&&typeof o=='object')return val(o,hit,0)}catch(e){}return esc(r.user)}
function pretty(r){if(r.answer_json){let t=JSON.stringify(r.answer_json,null,2);if(r.spelled.length)t+='\\n= '+r.spelled.join('; ');return t}return r.answer||''}
function label(r){return [r.kind,r.parameter||'',r.coordinate||''].filter(Boolean).join(' · ')}
function sub(r){return (r.owner!==undefined?'passage '+r.owner+' · ':'')+(r.value!==undefined?'value '+r.value+(r.at?' @'+r.at:'')+' · ':'')+(r.ms!==undefined?Math.round(r.ms)+' ms · ':'')+(r.prompt_tokens||'?')+'/'+(r.completion_tokens||'?')+' tok'+(r.attempt>1?' · attempt '+r.attempt:'')}
function plain(r){const lines=['## instruction',r.system,'','## request',r.user];r.messages.slice(1).forEach(m=>{lines.push('','## '+m[0],m[1])});
 lines.push('','## answer',r.answer===null?'(none)':pretty(r),'','## result',r.check);return lines.join('\\n')}
function list(){const k=$('fk').value,f=$('ff').value,o=$('fo').value.trim(),v=$('fv').value.trim(),q=$('q').value.toLowerCase();
 const el=$('items');el.innerHTML='';
 R.forEach((r,i)=>{if(view&&!view.includes(i))return;if(k&&r.kind!=k)return;if(f&&r.parameter!=f)return;if(o&&String(r.owner)!=o)return;if(v&&String(r.value)!=v)return;
  if(q&&!(r.system+r.user+(r.answer||'')+label(r)).toLowerCase().includes(q))return;
  const d=document.createElement('div');d.className='item'+(i==cur?' on':'');d.innerHTML='<b>'+esc(label(r))+'</b><small>'+esc(sub(r))+'</small><small>'+esc(r.check)+'</small>';
  d.onclick=()=>{cur=i;show(i);list()};el.appendChild(d)})}
function show(i){const r=R[i];const hit=addrs(r.answer_json);const ch=$('chat');
 let h='<h3>'+esc(label(r))+(r.asked?' (asks again: '+esc(r.asked)+')':'')+'</h3><p style="color:var(--muted)">#'+i+' · doc '+esc(r.doc)+' · '+esc(sub(r))+'</p>';
 h+='<button id="cp">Copy as text</button>';
 if(['coord','search','check','follow'].includes(r.kind))h+='<button id="ch">Chain of this value</button>';
 if(view)h+='<button id="all">Show all</button>';
 h+='<details class="msg system"><summary class="role">instruction</summary>'+esc(r.system)+'</details>';
 h+='<div class="msg user"><div class="role">request</div>'+userHtml(r,hit)+'</div>';
 r.messages.slice(1).forEach(m=>{h+='<div class="msg '+(m[0]=='assistant'?'assistant':'user')+'"><div class="role">'+esc(m[0])+' (this attempt)</div>'+esc(m[1])+'</div>'});
 h+='<div class="msg assistant"><div class="role">answer'+(r.finish?' · '+esc(r.finish):'')+'</div>'+(r.answer===null?esc(r.error||'no answer'):esc(pretty(r)))+'</div>';
 h+='<div class="msg check"><div class="role">result</div>'+esc(r.check)+'</div>';
 ch.innerHTML=h;ch.scrollTop=0;
 $('cp').onclick=()=>{const t=plain(r);(navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).catch(()=>{const a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();document.execCommand('copy');a.remove()})};
 if($('ch'))$('ch').onclick=()=>{view=r.chain;list();show(i)};
 if($('all'))$('all').onclick=()=>{view=null;list();show(i)}}
['fk','ff'].forEach(x=>$(x).onchange=list);['fo','fv','q'].forEach(x=>$(x).oninput=list);
list();if(R.length){cur=0;show(0);list()}
</script></body></html>"""


def render(requests: list) -> str:
    rows = [dict(r, chain=chain_of(requests, i)) for i, r in enumerate(requests)]
    data = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    return PAGE.replace("__DATA__", data)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("trace")
    ap.add_argument("out")
    ap.add_argument("--kind", action="append", help="request kind, e.g. coord or coord_ask")
    ap.add_argument("--field", action="append", help="parameter")
    ap.add_argument("--owner", action="append", help="passage id")
    ap.add_argument("--value", action="append", help="row label of the value")
    ap.add_argument("--contains", action="append", help="text anywhere in the request")
    ap.add_argument("--limit", type=int, default=400)
    a = ap.parse_args(argv)
    events = list(trace.lines(a.trace))
    reqs = requests_of(events)
    chosen = [r for r in reqs if _keep(r, a)][:a.limit]
    out = Path(a.out)
    out.write_text(render(chosen), encoding="utf-8")
    print(f"{len(chosen)} requests of {len(reqs)} -> {out} "
          f"{out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
