const $ = id => document.getElementById(id);
const alerts = [
  'checkout-api: HTTP 503; java.sql.SQLTransientConnectionException: HikariPool-1 connection is not available, request timed out after 30000ms',
  'checkout-api: HikariPool-1 timeout after 30000ms. PostgreSQL active connections at pool limit; errors increased after deployment.',
  'checkout-api: HikariPool connection acquisition timeout. Order lookup requests began failing after release v43; database connections remain idle.',
  'checkout-api: 503 and HikariPool-1 exhausted. Order lookup deploy v44 preceded rising idle PostgreSQL connections.',
  'checkout-api: SQLTransientConnectionException HikariPool-1. Order lookup deploy v45 correlated with connection exhaustion and elevated 503s.'
];
let scenarioIndex = -1;
let running = false;
const escapeHTML = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function post(url, body) {
  const response = await fetch(url, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Request failed. Check your input.');
  return data;
}
function renderCard(result, alert) {
  const a = result.answer;
  const card = document.createElement('article'); card.className='card';
  card.innerHTML = `<div class="card-head"><h3>${result.memory_enabled ? '✦ With memory' : 'Without memory'}</h3><span class="badge">${escapeHTML(a.confidence)} confidence</span></div>
    ${result.memory_warning ? `<div class="warning">${escapeHTML(result.memory_warning)}</div>` : ''}
    <h4>Likely root cause</h4><p>${escapeHTML(a.likely_root_cause)}</p><h4>Recommended steps</h4><ol>${a.recommended_fix_steps.map(s=>`<li>${escapeHTML(s)}</li>`).join('')}</ol>
    <h4>Recalled memories · ${result.memories.length}</h4>${result.memories.length ? result.memories.map(m=>`<div class="memory"><b>${escapeHTML(m.id)}${a.based_on.includes(m.id) ? ' · cited' : ''}</b><br>${escapeHTML(m.text)}${m.source ? `<details><summary>Source context</summary>${escapeHTML(m.source)}</details>` : ''}</div>`).join('') : '<p class="muted">No memories supplied to this answer.</p>'}
    <div class="feedback"><b>Did this suggestion work?</b><textarea aria-label="Feedback notes" placeholder="Add outcome notes (optional)"></textarea><div><button class="secondary worked">✓ Worked</button><button class="secondary failed">✕ Didn’t work</button></div><p class="feedback-status" role="status"></p></div>`;
  async function feedback(worked) {
    const status=card.querySelector('.feedback-status'); status.textContent='Saving to Hindsight…';
    try { const data=await post('/api/feedback',{alert,suggestion:a,worked,notes:card.querySelector('textarea').value}); status.textContent=`Saved as ${data.incident_id}. Recall indexing may take time.`; }
    catch(e){status.textContent=e.message;}
  }
  card.querySelector('.worked').onclick=()=>feedback(true); card.querySelector('.failed').onclick=()=>feedback(false);
  return card;
}
async function run() {
  if(running) return;
  const alert=$('alert').value.trim(); if(alert.length<5){$('error').textContent='Enter an alert of at least 5 characters.';return;}
  running=true; $('triage').disabled=true; $('next').disabled=true; $('error').textContent=''; $('triage').textContent='Analyzing…';
  try {
    const compare=$('compare').checked;
    const results=[];
    for (const memory of (compare ? [false,true] : [true])) {
      results.push(await post('/api/triage',{alert,memory}));
    }
    $('cards').replaceChildren(...results.map(r=>renderCard(r,alert))); $('results').hidden=false; $('results').scrollIntoView({behavior:'smooth',block:'start'});
  } catch(e){$('error').textContent=e.message;}
  finally{running=false;$('triage').disabled=false;$('next').disabled=false;$('triage').innerHTML='Run triage <span>→</span>';}
}
$('triage').onclick=run;
$('example').onclick=()=>{$('alert').value=alerts[0]};
$('next').onclick=async()=>{
  scenarioIndex=(scenarioIndex+1)%alerts.length; $('step').textContent=`${scenarioIndex+1} / 5`; $('alert').value=alerts[scenarioIndex];
  $('compare').checked=scenarioIndex===0;
  $('next').textContent=scenarioIndex===4?'Restart scenario →':'Next incident →';
  $('scenario-note').textContent='After reviewing, submit worked or failed feedback above before advancing. This demo writes feedback to your configured bank.';
  await run();
};
