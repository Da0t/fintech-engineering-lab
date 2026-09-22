const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = cents => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD'}).format(cents / 100);
const number = n => new Intl.NumberFormat('en-US').format(n);
const uid = prefix => `${prefix}_${crypto.randomUUID().slice(0, 12)}`;
const time = stamp => new Date(stamp).toLocaleTimeString('en-US', {hour:'2-digit',minute:'2-digit',second:'2-digit'});
let page = location.pathname === '/marketlab' ? 'market' : 'ledger';
let ledger, market, execution, inspection = null, busy = false, playing = false, timer, toastTimer;
let pendingOrder = null;
let publicDemo = false;
const sandboxSessions = {};
let formDraft = {side:'buy',type:'market',quantity:'50',limit:'100.00'};

function sandbox(project) {
  if (!sandboxSessions[project]) {
    try { sandboxSessions[project] = JSON.parse(sessionStorage.getItem('fintech-demo-v1-'+project)); } catch (_) { /* Storage is optional. */ }
    if (!sandboxSessions[project]) sandboxSessions[project] = {version:1,started_at:new Date().toISOString(),history:[]};
  }
  return sandboxSessions[project];
}

async function api(path, body) {
  const project = path.startsWith('/api/ledger/') ? 'ledger' : 'market';
  const target = publicDemo ? '/api/demo' : path;
  const requestBody = publicDemo ? {path,body:body ?? null,session:sandbox(project)} : body;
  const response = await fetch(target, {method: requestBody === undefined ? 'GET' : 'POST', headers:{'Content-Type':'application/json'}, ...(requestBody === undefined ? {} : {body:JSON.stringify(requestBody)})});
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Invalid input. Check the amounts and identifiers.');
  if (publicDemo) {
    sandboxSessions[project] = result.session;
    try { sessionStorage.setItem('fintech-demo-v1-'+project, JSON.stringify(result.session)); } catch (_) { /* In-memory sandbox still works. */ }
    return result.value;
  }
  return result;
}
function toast(message, error=false) {
  clearTimeout(toastTimer);
  const element = $('#toast'); element.textContent = message; element.hidden = false; element.classList.toggle('error', error);
  toastTimer = setTimeout(() => element.hidden = true, error ? 9000 : 6500);
}
function dollars(value) {
  if (!/^\d+(\.\d{1,2})?$/.test(String(value))) throw new Error('Enter a positive dollar amount with at most two decimal places.');
  const [whole, fraction=''] = String(value).split('.');
  const cents = Number(whole)*100 + Number(fraction.padEnd(2,'0'));
  if (!Number.isSafeInteger(cents) || cents <= 0) throw new Error('Amount must be positive.');
  return cents;
}
async function action(work) {
  if (busy) return;
  busy = true;
  document.querySelectorAll('button').forEach(b => b.disabled = true);
  try { await work(); }
  catch (error) { toast(error.message, true); }
  finally { busy = false; document.querySelectorAll('button').forEach(b => b.disabled = false); }
}
async function load() {
  if (page === 'ledger') ledger = await api('/api/ledger/state');
  else market = await api('/api/market/state');
  render();
}
function render() {
  document.querySelectorAll('[data-page]').forEach(a => {
    a.classList.toggle('active', a.dataset.page === page);
    if (a.dataset.page === page) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  $('#breadcrumb').textContent = page === 'ledger' ? 'CLEARLEDGER' : 'MARKETLAB';
  document.title = `${page === 'ledger' ? 'ClearLedger' : 'MarketLab'} · Fintech Engineering Lab`;
  $('#main').innerHTML = page === 'ledger' ? renderLedger() : renderMarket();
}
function stat(label, value, foot, featured=false) {
  return `<div class="stat ${featured?'featured':''}"><div class="label">${label}<span>↗</span></div><div class="value">${value}</div><div class="stat-foot">${foot}</div></div>`;
}
function badge(label, tone='') { return `<span class="badge ${tone}">${esc(label)}</span>`; }
function checks(data, descriptions) {
  return `<div class="health-list">${Object.entries(descriptions).map(([key, [label, sub]]) => `<div class="health-row"><span class="check ${data[key]?'':'fail'}">${data[key]?'✓':'!'}</span><div><strong>${label}</strong><small>${sub}</small></div><span class="mono ${data[key]?'green':'red'}">${data[key]?'PASS':'FAIL'}</span></div>`).join('')}</div>`;
}
function timeline(rows) {
  return rows.length ? `<div class="timeline">${rows.map(r => `<div class="timeline-item"><span class="timeline-marker"></span><div><strong>${esc(r.action || r.type)}</strong><p>${esc(r.detail)}</p><small>${r.created_at ? time(r.created_at) : 'TICK '+r.tick}${r.reference?' · '+esc(r.reference):''}</small></div></div>`).join('')}</div>` : '<div class="empty">Your next action starts the story.</div>';
}

function renderLedger() {
  const mismatch = ledger.reconciliation.filter(r => r.status !== 'matched');
  const pending = ledger.inbox.filter(e => e.status !== 'completed');
  const allGood = Object.values(ledger.checks).every(Boolean);
  return `<div class="page-header"><div><div class="tag">01 / TRANSACTION INFRASTRUCTURE</div><h1>Every dollar. <span>Accounted for.</span></h1><p class="subtitle">A working ledger with a paper trail. Trace transactions, recover failures, and reconcile the difference.</p></div><div class="header-actions"><button data-action="deposit-form">＋ Simulate deposit</button><button class="primary" data-action="refund-form">Issue refund ↗</button></div></div>
  <div class="intro-strip"><div><strong>Start with a failure.</strong> <span>Send a payment three times, interrupt the worker, then recover it without double-crediting.</span></div><button data-action="incident">Run failure scenario →</button></div>
  <section class="stats" aria-label="Ledger metrics">
    ${stat('Available balance',money(ledger.balances.wallet),'USD · spendable funds',true)}
    ${stat('Reserved funds',money(ledger.balances.reserved),`${ledger.holds.filter(h=>h.state==='reserved').length} active holds`)}
    ${stat('Reconciliation breaks',String(mismatch.length),mismatch.length?'Requires investigation':'All provider records matched')}
    ${stat('Ledger integrity',allGood?'Balanced':'Check failed',`${Object.values(ledger.checks).filter(Boolean).length} / 4 invariants passing`)}
  </section>
  ${inspection ? `<section class="panel inspector"><div class="panel-header"><h2>Inspecting <span class="mono">${esc(inspection)}</span></h2><button class="compact" data-action="close-inspection">Close ×</button></div><div class="panel-body">${timeline(ledger.audit.filter(r=>r.reference===inspection))}</div></section>`:''}
  <div class="section-grid"><section class="panel"><div class="panel-header"><div><h2>Provider reconciliation</h2><small>Internal postings compared with the simulated provider statement</small></div>${badge(mismatch.length ? mismatch.length+' breaks' : 'All matched',mismatch.length?'warn':'good')}</div><div class="table-wrap"><table><thead><tr><th>PAYMENT / TYPE</th><th class="right">INTERNAL</th><th class="right">PROVIDER</th><th>STATUS</th></tr></thead><tbody>${ledger.reconciliation.map(r=>`<tr class="inspectable" data-inspect="${esc(r.payment_id)}"><td><button class="compact ghost" data-action="inspect" data-id="${esc(r.payment_id)}">${esc(r.payment_id)}</button><br><small class="muted">${esc(r.kind)}</small></td><td class="right amount">${money(r.internal)}</td><td class="right amount">${money(r.provider)}</td><td>${badge(r.status,r.status==='matched'?'good':'warn')}${r.kind==='refund' && r.internal>r.provider?`<br><button class="compact ghost" style="margin-top:5px" data-action="provider-refund" data-id="${esc(r.payment_id)}" data-amount="${r.internal-r.provider}">Simulate provider acknowledgment</button>`:''}</td></tr>`).join('')}</tbody></table></div><div class="panel-footer">Compared on payment ID + type · Click a payment to inspect its audit trail</div></section>
  <section class="panel"><div class="panel-header"><h2>Correctness, continuously checked</h2><span class="code-pill">INVARIANTS</span></div><div class="panel-body">${checks(ledger.checks, {balanced:['Balanced journal','Every debit has an equal credit'],nonnegative_wallet:['Protected balances','Available funds cannot go negative'],holds_reconciled:['Holds reconciled','Reserved balance equals active holds'],refunds_bounded:['Refund limits','Refunds never exceed a payment']})}<div class="mini-label">POSTING MODEL</div><div class="flow"><span>Provider clearing</span><span>→</span><span>Paired journal entry</span><span>→</span><span>Wallet</span></div></div></section></div>
  <div class="section-grid"><section class="panel"><div class="panel-header"><div><h2>Journal</h2><small>Append-only money movement. Original entries are never rewritten.</small></div><span class="metric-inline">${ledger.journal.length} postings shown</span></div><div class="table-wrap"><table><thead><tr><th>REFERENCE</th><th>FLOW</th><th class="right">AMOUNT</th><th>TYPE</th></tr></thead><tbody>${ledger.journal.map(r=>`<tr class="inspectable" data-inspect="${esc(r.reference)}"><td class="mono">${esc(r.reference)}<br><small class="muted">${time(r.created_at)}</small></td><td><span class="muted">${esc(r.debit)}</span> → ${esc(r.credit)}</td><td class="right amount">${money(r.amount)}</td><td>${badge(r.kind)}</td></tr>`).join('')}</tbody></table></div></section>
  <section class="panel"><div class="panel-header"><h2>Event trail</h2><span class="metric-inline">LATEST ACTIVITY</span></div><div class="panel-body">${timeline(ledger.audit.slice(0,12))}</div></section></div>
  <div class="section-grid"><section class="panel"><div class="panel-header"><div><h2>Recovery inbox</h2><small>Durable events survive a worker interruption</small></div>${badge(pending.length+' pending / failed',pending.length?'warn':'good')}</div>${pending.length?pending.map(e=>`<div class="pending-row"><div class="row"><strong>${esc(e.payment_id)}</strong><span class="amount">${money(e.amount)}</span></div><p>${esc(e.error || 'Waiting for the worker')} · ${e.attempts} attempt${e.attempts===1?'':'s'}</p><button class="compact primary" data-action="retry" data-id="${esc(e.id)}">Retry event →</button></div>`).join(''):'<div class="empty">No events waiting for recovery.<span>Run the failure scenario above to create one.</span></div>'}</section>
  <section class="panel"><div class="panel-header"><h2>Funds reservations</h2><button class="compact" data-action="hold-form">＋ Reserve</button></div><div class="panel-body">${ledger.holds.length?ledger.holds.map(h=>`<div class="hold-row"><div class="row"><span class="mono">${esc(h.id)}</span><span class="amount">${money(h.amount)}</span></div><div class="row" style="margin-top:8px">${badge(h.state,h.state==='reserved'?'warn':'good')}${h.state==='reserved'?`<div class="controls"><button class="compact" data-action="resolve-hold" data-id="${esc(h.id)}" data-resolve="release">Release</button><button class="compact" data-action="resolve-hold" data-id="${esc(h.id)}" data-resolve="settle">Settle</button></div>`:''}</div></div>`).join(''):'<div class="empty">No reservations yet.</div>'}</div></section></div>`;
}

function chart(prices) {
  const data=prices.slice(-100), w=740,h=172,p=8;
  const low=Math.min(...data.map(d=>d.price))-8, high=Math.max(...data.map(d=>d.price))+8;
  const points=data.map((d,i)=>`${p+(data.length===1?0:i/(data.length-1))*(w-2*p)},${h-p-(d.price-low)/(high-low)*(h-2*p)}`);
  if (points.length===1) points.push(`${w-p},${points[0].split(',')[1]}`);
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="Synthetic reference price history. Current price ${money(prices.at(-1).price)}"><defs><linearGradient id="area" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#d95532" stop-opacity=".16"/><stop offset="100%" stop-color="#d95532" stop-opacity="0"/></linearGradient></defs>${[.15,.5,.85].map(y=>`<line x1="0" y1="${h*y}" x2="${w}" y2="${h*y}" stroke="#e9ece4" stroke-dasharray="3 5"/>`).join('')}<polygon points="${p},${h} ${points.join(' ')} ${w-p},${h}" fill="url(#area)"/><polyline points="${points.join(' ')}" fill="none" stroke="#d95532" stroke-width="2" vector-effect="non-scaling-stroke"/></svg><div class="chart-labels"><span>TICK ${data[0].tick}</span><span>${data.length===1?'Press play to generate the session':'SYNTHETIC REFERENCE PRICE · USD'}</span><span>TICK ${data.at(-1).tick}</span></div>`;
}
function depth(rows, side) {
  const max=Math.max(...rows.map(r=>r.quantity),1);
  return `<div><div class="depth-header"><span>${side==='bid'?'BID':'ASK'} (USD)</span><span>QTY</span></div>${rows.length?rows.slice(0,10).map(r=>`<div class="depth-row ${side}" style="--depth:${r.quantity/max*95}%"><span class="${side==='bid'?'green':'orange'}">${money(r.price)}${r.user_quantity?' •':''}</span><span>${number(r.quantity)}</span></div>`).join(''):'<div class="empty">No liquidity</div>'}</div>`;
}
function executionDetails() {
  if(!execution || execution.duplicate) return '<div class="execution-empty">Place an order to see its fills, execution price, and fees.</div>';
  const fills=execution.fills || [], qty=fills.reduce((sum,f)=>sum+f.quantity,0), total=fills.reduce((sum,f)=>sum+f.quantity*f.price,0), fee=fills.reduce((sum,f)=>sum+f.fee,0);
  if(!qty) return `<div class="execution-empty">No immediate fills. ${execution.unfilled} shares ${formDraft.type==='limit'?'remain on the book at your limit price':'were cancelled because there was no liquidity'}.</div>`;
  const side=fills[0].side, sign=side==='buy'?1:-1, avg=total/qty;
  const spread=execution.reference_mid===null || execution.reference_best===null ? null : sign*(execution.reference_best-execution.reference_mid)*qty;
  const impact=execution.reference_best===null ? null : sign*(avg-execution.reference_best)*qty;
  return `<div class="explanation"><div class="row"><span class="muted">Order</span><span class="mono">${esc(execution.order_id)}</span></div><div class="row"><span>Filled / requested</span><span class="mono">${qty} / ${execution.requested}</span></div><div class="row"><span>Average execution</span><span class="amount">${money(avg)}</span></div><div class="row"><span>Spread cost vs. arrival midpoint</span><span class="amount">${spread===null?'N/A':money(spread)}</span></div><div class="row"><span>Book depth impact vs. best quote</span><span class="amount">${impact===null?'N/A':money(impact)}</span></div><div class="row"><span>Fees · 10 bps, rounded per fill</span><span class="amount">${money(fee)}</span></div><div class="row total"><span>${side==='buy'?'Total paid':'Net proceeds'}</span><span class="amount">${money(total+(side==='buy'?fee:-fee))}</span></div></div><p class="muted" style="font-size:10px;margin-bottom:0">Breakdown is for immediate fills at submission. Later fills on resting orders appear in the tape below.</p>`;
}
function renderMarket() {
  const s=market.state;
  return `<div class="page-header"><div><div class="tag">02 / MARKET MICROSTRUCTURE</div><h1>The price is only <span>the beginning.</span></h1><p class="subtitle">Replay a market. Place a paper order. Follow every fill from the order book to your balance.</p></div><div class="header-actions"><button data-action="replay">↶ Verify replay</button><button data-action="feed" class="${s.connected?'':'primary'}">${s.connected?'Disconnect feed':'Reconnect feed'}</button></div></div>
  <div class="intro-strip"><div><strong>Same order. Different market.</strong> <span>Try a 50-share market buy in both liquidity modes and compare execution costs.</span></div><span class="mono">NOVA · SYNTHETIC INSTRUMENT</span></div>
  <section class="stats" aria-label="Trading metrics">${stat('Reference price',money(s.mid),`NOVA · tick ${s.tick}`,true)}${stat('Available buying power',money(s.available_cash),`${money(s.reserved_cash)} reserved`)}${stat('Position',number(s.position)+' <span style="font-size:15px;letter-spacing:0">shares</span>',`${s.available_position} available to sell`)}${stat('Execution fees',money(s.fees),`${s.fills.length} fills · 10 basis points`)}</section>
  <div class="market-grid"><div class="market-left"><section class="panel"><div class="panel-header"><div><h2>Session replay</h2><small>A deterministic synthetic market, advanced one tick at a time</small></div><div class="controls"><button class="compact ${playing?'accent':'primary'}" data-action="play">${playing?'Ⅱ Pause':'▶ Play'}</button><button class="compact" data-action="step">+ 10 ticks</button></div></div><div class="chart-area"><div class="chart-meta"><span>${s.connected?'<span class="status-dot"></span>Feed connected':'<span class="orange">Feed disconnected · order entry blocked</span>'}</span><span class="mono">BOOK SNAPSHOT: T${s.feed_tick}</span></div>${chart(s.prices)}</div><div class="panel-footer row"><span>Simulation clock · no live market connection</span><span>${market.commands} accepted commands</span></div></section>
  <section class="panel"><div class="panel-header"><div><h2>Order book</h2><small>Price / time priority · dots identify your resting liquidity</small></div><div class="tabs" aria-label="Liquidity mode"><button class="${s.liquidity==='liquid'?'selected':''}" data-action="liquidity" data-mode="liquid">Liquid</button><button class="${s.liquidity==='thin'?'selected':''}" data-action="liquidity" data-mode="thin">Thin</button></div></div><div class="depth-grid">${depth(s.bids,'bid')}${depth(s.asks,'ask')}</div><div class="panel-footer">Changing liquidity starts a fresh paper session, including balances and orders.</div></section>
  <section class="panel"><div class="panel-header"><h2>Open orders</h2><span class="metric-inline">${s.orders.length} RESTING</span></div>${s.orders.length?`<div class="table-wrap"><table><thead><tr><th>ORDER</th><th>SIDE</th><th>LIMIT</th><th>REMAINING</th><th></th></tr></thead><tbody>${s.orders.map(o=>`<tr><td class="mono">${esc(o.id)}</td><td>${badge(o.side,o.side==='buy'?'good':'warn')}</td><td class="amount">${money(o.price)}</td><td class="mono">${o.remaining}</td><td><button class="compact" data-action="cancel" data-id="${esc(o.id)}">Cancel</button></td></tr>`).join('')}</tbody></table></div>`:'<div class="empty">No resting orders.<span>Submit a limit order away from the market to reserve buying power.</span></div>'}</section></div>
  <div class="market-left"><section class="panel"><div class="panel-header"><h2>Order ticket</h2>${badge('PAPER ONLY')}</div><div class="panel-body"><form class="order-form" id="order-form"><div class="fields-two"><div class="field"><label for="side">Side</label><select id="side" name="side"><option value="buy" ${formDraft.side==='buy'?'selected':''}>Buy</option><option value="sell" ${formDraft.side==='sell'?'selected':''}>Sell</option></select></div><div class="field"><label for="type">Order type</label><select id="type" name="type"><option value="market" ${formDraft.type==='market'?'selected':''}>Market</option><option value="limit" ${formDraft.type==='limit'?'selected':''}>Limit</option></select></div></div><div class="fields-two"><div class="field"><label for="quantity">Quantity (shares)</label><input id="quantity" name="quantity" type="number" min="1" max="10000" step="1" required value="${esc(formDraft.quantity)}"></div><div class="field" id="limit-field" ${formDraft.type==='market'?'hidden':''}><label for="limit">Limit price (USD)</label><input id="limit" name="limit" inputmode="decimal" value="${esc(formDraft.limit)}"></div></div><button class="primary" type="submit">Submit paper order →</button><div class="order-note">Whole shares · no leverage or short selling. Unfilled market quantity is cancelled. Limit orders reserve funds until filled or cancelled.</div></form></div></section>
  <section class="panel"><div class="panel-header"><h2>Why this execution price?</h2><span class="code-pill">FILL ANALYSIS</span></div><div class="panel-body">${executionDetails()}</div></section>
  <section class="panel"><div class="panel-header"><h2>Engine integrity</h2><span class="code-pill">JAVA</span></div><div class="panel-body">${checks(s.checks,{cash_reconciled:['Cash reconciled','Balance matches every fill and fee'],position_reconciled:['Position reconciled','Holdings match executed quantities'],nonnegative_buying_power:['Buying power protected','Open orders reserve sufficient funds'],no_overselling:['No overselling','Sell orders reserve available shares'],uncrossed_book:['Uncrossed book','Best bid remains below best ask']})}</div></section></div></div>
  <div class="section-grid"><section class="panel"><div class="panel-header"><div><h2>Execution tape</h2><small>Actual simulated fills from the Java matching engine</small></div><span class="metric-inline">LATEST 20</span></div>${s.fills.length?`<div class="table-wrap"><table><thead><tr><th>TICK / ORDER</th><th>SIDE</th><th class="right">QTY</th><th class="right">PRICE</th><th class="right">FEE</th></tr></thead><tbody>${s.fills.slice(-20).reverse().map(f=>`<tr><td class="mono">T${f.tick} · ${esc(f.order_id)}<br><small class="muted">${f.liquidity}</small></td><td>${badge(f.side,f.side==='buy'?'good':'warn')}</td><td class="right mono">${f.quantity}</td><td class="right amount">${money(f.price)}</td><td class="right amount">${money(f.fee)}</td></tr>`).join('')}</tbody></table></div>`:'<div class="empty">The tape is clear.<span>Submit your first paper order to see its individual fills.</span></div>'}</section><section class="panel"><div class="panel-header"><h2>Session events</h2><span class="metric-inline">LATEST ACTIVITY</span></div><div class="panel-body">${timeline(s.events.slice(-12).reverse())}</div></section></div>`;
}

function openForm(kind) {
  const refund=kind==='refund', hold=kind==='hold';
  const title=refund?'Issue a partial refund':hold?'Reserve funds':'Simulate a deposit';
  const choices=ledger.payments.filter(p=>p.refunded<p.amount);
  $('#dialog-content').innerHTML=`<h2 id="dialog-title">${title}</h2><p class="dialog-subtitle">${refund?'Posts a reversal without modifying the original deposit. Provider acknowledgment is simulated separately.':hold?'Moves available cash into a protected reservation until you settle or release it.':'Creates a provider statement record and processes a synthetic payment event.'}</p><form id="ledger-form" data-kind="${kind}" data-key="${uid(kind)}">${refund?`<div class="field"><label for="payment">Original payment</label><select id="payment" name="payment">${choices.map(p=>`<option value="${esc(p.id)}">${esc(p.id)} · ${money(p.amount-p.refunded)} refundable</option>`).join('')}</select></div>`:''}<div class="field"><label for="amount">Amount (USD)</label><input name="amount" id="amount" inputmode="decimal" required pattern="[0-9]+(\.[0-9]{1,2})?" placeholder="${refund?'25.00':hold?'50.00':'250.00'}"><small>USD only. Amounts are stored as integer cents.</small></div><div class="dialog-actions"><button type="button" data-action="close-dialog">Cancel</button><button class="primary" type="submit">${refund?'Post refund':hold?'Reserve funds':'Process deposit'} →</button></div></form>`;
  $('#form-dialog').showModal();
  $('#amount').focus();
}
function stop() { playing=false; clearTimeout(timer); }
async function playTick() {
  if(!playing || page!=='market') return;
  if(busy || $('#order-form')?.contains(document.activeElement)) { timer=setTimeout(playTick,500); return; }
  busy=true;
  try { market=await api('/api/market/step',{ticks:1}); render(); }
  catch(error) { stop(); toast(error.message,true); render(); }
  finally { busy=false; }
  if(playing) timer=setTimeout(playTick,500);
}

document.addEventListener('click', async event => {
  const link=event.target.closest('[data-page]');
  if(link) {
    if(event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); if(busy) return;
    stop(); page=link.dataset.page; history.pushState({},'',link.href);
    await action(load); return;
  }
  const button=event.target.closest('[data-action]');
  if(!button) {
    const row=event.target.closest('[data-inspect]');
    if(row && !busy) { inspection=row.dataset.inspect; render(); }
    return;
  }
  const a=button.dataset.action, id=button.dataset.id;
  if(a==='close-dialog') { $('#form-dialog').close(); return; }
  if(a.endsWith('-form')) { openForm(a.replace('-form','')); return; }
  if(a==='inspect') { inspection=id; render(); return; }
  if(a==='close-inspection') { inspection=null; render(); return; }
  await action(async () => {
    if(a==='new-session') {
      stop(); sandboxSessions[page]={version:1,started_at:new Date().toISOString(),history:[]};
      try { sessionStorage.removeItem('fintech-demo-v1-'+page); } catch (_) {}
      execution=null; pendingOrder=null; inspection=null;
      await load(); toast('New sandbox ready. Only this tab’s session was reset.');
    }
    if(a==='incident') { const r=await api('/api/ledger/incident',{}); await load(); toast(r.message); }
    if(a==='retry') { await api(`/api/ledger/events/${encodeURIComponent(id)}/retry`,{}); await load(); toast('Recovered. Payment posted once; provider and ledger now reconcile.'); }
    if(a==='resolve-hold') { await api(`/api/ledger/holds/${encodeURIComponent(id)}/resolve`,{action:button.dataset.resolve,key:uid('resolve')}); await load(); toast('Reservation '+(button.dataset.resolve==='settle'?'settled.':'released.')); }
    if(a==='provider-refund') { await api('/api/ledger/provider-records',{record_id:uid('statement'),payment_id:id,kind:'refund',amount:Number(button.dataset.amount)}); await load(); toast('Simulated provider refund acknowledgment imported.'); }
    if(a==='step') { market=await api('/api/market/step',{ticks:10}); render(); }
    if(a==='play') { if(playing) stop(); else { playing=true; timer=setTimeout(playTick,500); } render(); }
    if(a==='replay') { stop(); market=await api('/api/market/replay',{}); render(); toast(`Replay verified: ${market.result.commands_replayed} commands rebuilt an identical state.`); }
    if(a==='feed') { const name=market.state.connected?'disconnect':'reconnect'; market=await api('/api/market/feed/'+name,{}); render(); toast(name==='disconnect'?'Feed paused. Advance ticks to create a gap, then reconnect.':`Feed recovered with a fresh snapshot. ${market.result.gap} missed ticks.`); }
    if(a==='liquidity') { stop(); market=await api('/api/market/reset',{liquidity:button.dataset.mode}); execution=null; pendingOrder=null; render(); toast('Fresh '+button.dataset.mode+' session. Cash and position reset.'); }
    if(a==='cancel') { market=await api(`/api/market/orders/${encodeURIComponent(id)}/cancel`,{}); render(); toast('Order cancelled. Remaining reservation released.'); }
  });
});
document.addEventListener('input', event => {
  if(event.target.closest('#order-form')) formDraft[event.target.name]=event.target.value;
});
document.addEventListener('change', event => {
  if(event.target.closest('#order-form')) {
    formDraft[event.target.name]=event.target.value;
    if(event.target.name==='type') $('#limit-field').hidden=event.target.value==='market';
  }
});
document.addEventListener('submit', event => {
  if(event.target.id==='order-form') {
    event.preventDefault();
    action(async () => {
      stop();
      const quantity=Number(formDraft.quantity);
      if(!Number.isInteger(quantity) || quantity<=0) throw new Error('Quantity must be a positive whole number.');
      const payload={side:formDraft.side,type:formDraft.type,quantity,limit:formDraft.type==='limit'?dollars(formDraft.limit):10000};
      const fingerprint=JSON.stringify(payload);
      if(!pendingOrder || pendingOrder.fingerprint!==fingerprint) pendingOrder={fingerprint,body:{id:uid('order'),...payload}};
      // A retry after a lost response retains the economic order's identity.
      market=await api('/api/market/orders',pendingOrder.body);
      pendingOrder=null;
      execution=market.result; render();
      toast(execution.duplicate?'Original order confirmed. The retry did not execute another trade.':`Order accepted. ${execution.filled} of ${execution.requested} shares filled immediately.`);
    });
  }
  if(event.target.id==='ledger-form') {
    event.preventDefault(); const form=event.target;
    action(async () => {
      const fields=new FormData(form), amount=dollars(fields.get('amount')), kind=form.dataset.kind, key=form.dataset.key;
      if(kind==='refund') await api('/api/ledger/refunds',{payment_id:fields.get('payment'),amount,key});
      else if(kind==='hold') await api('/api/ledger/holds',{hold_id:key,amount});
      else {
        await api('/api/ledger/provider-records',{record_id:'statement_'+key,payment_id:key,kind:'deposit',amount});
        await api('/api/ledger/events',{event_id:'evt_'+key,payment_id:key,amount});
        await api('/api/ledger/events/evt_'+encodeURIComponent(key)+'/retry',{});
      }
      $('#form-dialog').close(); await load(); toast(kind==='refund'?'Refund posted. A reconciliation break remains until the simulated provider acknowledges it.':kind==='hold'?'Funds reserved.':'Deposit posted and reconciled.');
    });
  }
});
window.addEventListener('popstate', () => { stop(); page=location.pathname==='/marketlab'?'market':'ledger'; action(load); });
async function initialize() {
  const config=await fetch('/api/config').then(r=>r.json());
  publicDemo=config.public_demo;
  if (publicDemo) {
    $('#new-session').hidden=false;
    $('.sidebar-bottom').innerHTML='<span class="status-dot"></span>Your demo session<small>Synthetic funds · isolated to this tab</small>';
    $('.sandbox-label').textContent='PUBLIC SANDBOX';
    $('footer span').textContent='Synthetic USD · session saved in this tab';
  }
  await load();
}
initialize().catch(error => { $('#main').innerHTML='<div class="loading">Unable to load the demo. Please reload or start a new session.</div>'; toast(error.message,true); });
