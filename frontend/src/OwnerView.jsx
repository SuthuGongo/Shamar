import { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import { OUTCOME } from './App.jsx'
import { ActivityChart, Icon, Kpi, OutcomeDonut, Panel, Shell, avClass, rand } from './ui.jsx'

const ALERT_PILL = {
  open: (a) => ({ text: a.level === 'hold' ? 'Held' : 'Needs a check', cls: a.level }),
  checking: () => ({ text: 'Checking', cls: 'check' }),
  cleared: () => ({ text: 'Cleared', cls: 'clear' }),
  held: () => ({ text: 'Blocked', cls: 'indigo' }),
}
const PAY_PILL = {
  held: { text: 'Held by Shamar', cls: 'hold' },
  awaiting_owner: { text: 'Ready to approve', cls: 'muted' },
  paid: { text: 'Paid', cls: 'clear' },
  blocked: { text: 'Blocked', cls: 'indigo' },
}

export default function OwnerView({ s, refresh, toast, shell }) {
  const [page, setPage] = useState('overview')
  const [selId, setSelId] = useState(null)
  const [live, setLive] = useState(null)
  const seen = useRef(null)
  useEffect(() => {
    const ids = s.alerts.map((a) => a.id)
    const first = seen.current === null
    if (first) seen.current = new Set()
    const fresh = s.alerts.find((a) => !seen.current.has(a.id) && a.status === 'open' && (!first || a.level === 'hold'))
    ids.forEach((id) => seen.current.add(id))
    if (fresh) { setLive(fresh); const t = setTimeout(() => setLive(null), 9000); return () => clearTimeout(t) }
  }, [s.alerts])
  const [payMsg, setPayMsg] = useState(null)
  const open = s.alerts.filter((a) => a.status === 'open' || a.status === 'checking')
  const sel = s.alerts.find((a) => a.id === selId) || open[0] || s.alerts[0]
  useEffect(() => { if (!selId && sel) setSelId(sel.id) }, [selId, sel])
  const review = (id) => { setSelId(id); setPage('alerts') }
  const heldPays = s.payments.filter((p) => p.status === 'held')

  const approve = async (p) => {
    try { await api.approve(p.id); setPayMsg({ ok: true, text: `${rand(p.amount)} to ${p.supplier} approved and sent to the bank.` }) }
    catch (e) { setPayMsg({ ok: false, text: e.message }) }
    refresh()
  }
  const nav = [
    { id: 'overview', label: 'Overview', icon: 'home' },
    { id: 'alerts', label: 'Alerts', icon: 'bell', badge: open.length || null },
    { id: 'payments', label: 'Payments', icon: 'card', badge: heldPays.length || null },
    { id: 'activity', label: 'Activity log', icon: 'list' },
    { id: 'team', label: 'Team & patterns', icon: 'users' },
    { id: 'settings', label: 'Settings', icon: 'shield' },
  ]
  const titles = {
    overview: open.length ? `Good morning, Thandi. ${open.length} ${open.length === 1 ? 'thing needs' : 'things need'} you.` : 'Good morning, Thandi. All clear.',
    alerts: 'Alerts', payments: 'Payments', activity: 'Activity log', team: 'What Shamar has learned', settings: 'Settings',
  }

  return (
    <Shell {...shell} nav={nav} page={page} setPage={setPage} title={titles[page]} clock={s.clock} day={s.day}>
      {live && (
        <div className="livealert" role="alert">
          <div className="row"><b>{live.level === 'hold' ? 'Shamar stopped this' : 'Shamar flagged this'}</b><button className="link" onClick={() => setLive(null)} aria-label="Dismiss">✕</button></div>
          <span style={{ fontWeight: 600 }}>{live.title}</span>
          <span className="who">{live.actor} · {live.time} · risk {live.score}/10</span>
          <button className="btn primary small" onClick={() => { review(live.id); setLive(null) }}>Review now</button>
        </div>
      )}
      {page === 'overview' && (
        <>
          <div className="kpis">
            <Kpi icon="shield" label="Actions checked today" value={s.counts.checked} sub="by Shamar" />
            <Kpi icon="check" label="Went straight through" value={s.counts.through} tone="clear" sub={s.counts.checked ? `${Math.round((s.counts.through / s.counts.checked) * 100)}% of all actions` : ' '} />
            <Kpi icon="bell" label="Need your decision" value={open.length} tone={open.length ? 'hold' : ''} sub={`${heldPays.length} held ${heldPays.length === 1 ? 'payment' : 'payments'}`} />
            <Kpi icon="money" label="Payments blocked" value={rand(s.counts.saved)} tone="indigo" sub="today" />
          </div>
          <div className="grid2">
            <Panel title="Activity today"><ActivityChart events={s.events} /></Panel>
            <Panel title="Outcomes"><OutcomeDonut events={s.events} /></Panel>
          </div>
          <div className="grid2">
            <Panel title="Needs your decision" action={open.length > 0 && <button className="btn soft small" onClick={() => setPage('alerts')}>See all</button>}>
              <AlertTable alerts={open} onReview={review} empty="Nothing needs you right now. Shamar is watching." />
            </Panel>
            <Panel title="Team status">
              <TeamList s={s} open={open} refresh={refresh} toast={toast} />
            </Panel>
          </div>
          <Forecast s={s} onMore={() => setPage('team')} />
        </>
      )}

      {page === 'alerts' && (
        <div className="split">
          <Panel title="All alerts">
            <ul className="alertlist">
              {s.alerts.length === 0 && <li className="empty">No alerts yet.</li>}
              {s.alerts.map((a) => {
                const pill = ALERT_PILL[a.status](a)
                return (
                  <li key={a.id}>
                    <button className={sel && a.id === sel.id ? 'on' : ''} onClick={() => setSelId(a.id)}>
                      <span className={`av ${avClass(a.actor_kind, a.actor_id)}`}>{a.actor[0]}</span>
                      <span className="what"><b>{a.title}</b><small>{a.actor} · {a.time} · risk {a.score}/10</small></span>
                      <span className={`pill ${pill.cls}`}>{pill.text}</span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </Panel>
          {sel ? <AlertCard a={sel} s={s} refresh={refresh} onDecided={() => setPayMsg(null)} /> : <Panel><p className="empty">Select an alert.</p></Panel>}
        </div>
      )}

      {page === 'payments' && (
        <Panel title="Payments">
          {payMsg && <div className={`note ${payMsg.ok ? 'bg-clear' : 'bg-hold'}`} role="status">{payMsg.text}</div>}
          <div className="tblwrap">
            <table className="tbl">
              <thead><tr><th>Time</th><th>Supplier</th><th>Account</th><th>Prepared by</th><th className="num">Amount</th><th>Status</th><th><span className="sr">Action</span></th></tr></thead>
              <tbody>
                {s.payments.length === 0 && <tr><td colSpan={7} className="empty">No payments yet today.</td></tr>}
                {s.payments.map((p) => (
                  <tr key={p.id}>
                    <td className="muted">{p.ts.slice(11, 16)}</td>
                    <td><b>{p.supplier}</b>{p.reference && <small className="block">{p.reference}</small>}</td>
                    <td className="mono">{p.account}</td>
                    <td>{p.by}</td>
                    <td className="num"><b>{rand(p.amount)}</b></td>
                    <td><span className={`pill ${PAY_PILL[p.status].cls}`}>{PAY_PILL[p.status].text}</span></td>
                    <td className="num">
                      {(p.status === 'held' || p.status === 'awaiting_owner') && <button className="btn plain small" onClick={() => approve(p)}>Approve</button>}
                      {p.alert_id && <button className="btn soft small" style={{ marginLeft: 6 }} onClick={() => review(p.alert_id)}>Why?</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {page === 'activity' && <ActivityLog s={s} onReview={review} />}

      {page === 'settings' && <SettingsPage toast={toast} refresh={refresh} />}

      {page === 'team' && (
        <>
          <Panel title="Who Shamar is watching">
            <TeamList s={s} open={open} refresh={refresh} toast={toast} detailed />
          </Panel>
          <Learned s={s} />
        </>
      )}
    </Shell>
  )
}

function AlertTable({ alerts, onReview, empty }) {
  if (!alerts.length) return <p className="empty">{empty}</p>
  return (
    <div className="tblwrap">
      <table className="tbl">
        <thead><tr><th>Time</th><th>Who</th><th>What</th><th className="num">Risk</th><th><span className="sr">Action</span></th></tr></thead>
        <tbody>
          {alerts.map((a) => (
            <tr key={a.id}>
              <td className="muted">{a.time}</td>
              <td>{a.actor}</td>
              <td><b>{a.title}</b></td>
              <td className="num"><span className={`pill ${a.level}`}>{a.score}/10</span></td>
              <td className="num"><button className="btn primary small" onClick={() => onReview(a.id)}>Review</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function TeamList({ s, open, refresh, toast, detailed }) {
  return (
    <ul className="teamlist">
      {s.actors.filter((a) => a.kind !== 'owner' && a.kind !== 'external').map((a) => {
        const flagged = open.filter((x) => x.actor_id === a.id).length
        const done = s.events.filter((e) => e.actor_id === a.id).length
        const status = a.paused ? { t: 'Paused', c: 'hold' } : flagged ? { t: `${flagged} alert${flagged > 1 ? 's' : ''}`, c: 'check' } : { t: 'All normal', c: 'clear' }
        return (
          <li key={a.id}>
            <span className={`av ${avClass(a.kind, a.id)}`}>{a.name[0]}</span>
            <span className="what"><b>{a.name}</b><small>{a.role}{detailed ? ` · ${done} actions today` : ''}</small></span>
            <span className={`pill ${status.c}`}>{status.t}</span>
            {a.paused ? <button className="btn soft small" onClick={async () => { await api.resume(a.id); toast(`${a.name} resumed`); refresh() }}>Resume</button> : null}
          </li>
        )
      })}
    </ul>
  )
}

function ActivityLog({ s, onReview }) {
  const [filter, setFilter] = useState('all')
  const rows = s.events.filter((e) => filter === 'all' || (e.outcome !== 'done'))
  return (
    <Panel title="Everything Shamar checked"
      action={<div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}><div className="seg">{['all', 'flagged'].map((f) => <button key={f} className={filter === f ? 'on' : ''} onClick={() => setFilter(f)}>{f === 'all' ? 'All' : 'Flagged & stopped'}</button>)}</div><button className="btn soft small" onClick={() => downloadCsv(rows, s.day)}>Download CSV</button></div>}>
      <div className="tblwrap">
        <table className="tbl">
          <thead><tr><th>Time</th><th>Who</th><th>Action</th><th>System</th><th className="num">Risk</th><th>Result</th><th><span className="sr">Action</span></th></tr></thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={7} className="empty">Nothing here yet.</td></tr>}
            {rows.map((e) => {
              const o = e.action === 'owner_decision' ? { text: 'Your decision', cls: 'indigo' } : OUTCOME[e.outcome]
              const al = s.alerts.find((a) => a.event_id === e.id)
              return (
                <tr key={e.id}>
                  <td className="muted">{e.time}</td>
                  <td><span className="who2"><span className={`av sm ${avClass(null, e.actor_id)}`}>{e.actor[0]}</span>{e.actor}</span></td>
                  <td>{e.summary}</td>
                  <td className="muted">{e.system}</td>
                  <td className="num">{e.score ? e.score : '–'}</td>
                  <td><span className={`pill ${o.cls}`}>{o.text}</span></td>
                  <td className="num">{al && <button className="btn soft small" onClick={() => onReview(al.id)}>Why?</button>}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}

function AlertCard({ a, s, refresh, onDecided }) {
  const [busy, setBusy] = useState(false)
  const pill = ALERT_PILL[a.status](a)
  const m = a.metric
  const [confirming, setConfirming] = useState(false)
  useEffect(() => { setConfirming(false) }, [a.id])
  const decide = async (d) => { setBusy(true); setConfirming(false); try { await api.decide(a.id, d); onDecided(); await refresh() } finally { setBusy(false) } }
  const isPay = !!a.payment_id
  const isAI = a.actor_kind === 'ai_agent'
  const L = isPay
    ? { clear: 'Release payment', check: 'Keep holding while I check', hold: 'Block payment' }
    : isAI ? { clear: 'It’s fine, resume ' + a.actor, check: 'Keep paused while I check', hold: 'Block and keep paused' }
      : { clear: 'It’s fine', check: 'I’ll check', hold: 'Block it' }
  const fmt = (v) => (m?.unit === 'R' ? rand(v) : String(v))
  const scale = m ? Math.max(m.hi, m.today) * 1.15 || 1 : 1
  const pc = (v) => `${Math.min(100, (v / scale) * 100).toFixed(1)}%`
  const actor = s.actors.find((x) => x.id === a.actor_id)
  return (
    <section className="panel alertcard" aria-label="Decision">
      <div className="row">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span className={`av ${avClass(a.actor_kind, a.actor_id)}`}>{a.actor[0]}</span>
          <span style={{ lineHeight: 1.3 }}><b>{a.actor}, {actor?.role}</b><br /><span className="who">Today, {a.time}</span></span>
        </div>
        <span className={`pill ${pill.cls}`}>{pill.text}</span>
      </div>
      <div>
        <h2>{a.title}</h2>
        <p className="line">{a.line}</p>
      </div>
      <div className="twocol">
        <div>
          <h3>Why Shamar flagged it</h3>
          {a.reasons.map((r, i) => (
            <div className="reason" key={i}><span className={`kind ${r.kind}`}>{r.kind}</span><span style={{ flex: 1 }}>{r.text}</span>{r.points > 0 && <span className="pts">+{r.points}</span>}</div>
          ))}
          <ScoreBar score={a.score} t={s.thresholds} />
          {m && (
            <div style={{ marginTop: 12 }}>
              <div className="row" style={{ fontSize: 13, flexWrap: 'wrap' }}>
                <b>{m.label}</b>
                <span className="who">usually {fmt(m.lo)}–{fmt(m.hi)} · <strong style={{ color: m.today > m.hi ? 'var(--hold)' : 'var(--clear)' }}>now {fmt(m.today)}</strong></span>
              </div>
              <div className="bar" aria-hidden="true">
                <div className="band" style={{ left: pc(m.lo), width: `calc(${pc(m.hi)} - ${pc(m.lo)})` }} />
                <div className="dot" style={{ left: pc(m.today), borderColor: m.today > m.hi ? '#E5484D' : '#3CCB7F' }} />
              </div>
            </div>
          )}
        </div>
        {a.chain?.length > 0 && (
          <div>
            <h3>What happened, in order</h3>
            <ol className="chain">
              {a.chain.map((c, i) => (
                <li key={i} className={c.tone}><span className="t">{c.time}</span><span>{c.text}</span></li>
              ))}
            </ol>
          </div>
        )}
      </div>
      <div className="note bg-indigo" style={{ fontWeight: 500 }}><b>Next step:</b> {a.next_step}</div>
      {a.note && <div className={`note ${a.status === 'cleared' ? 'bg-clear' : a.status === 'checking' ? 'bg-check' : 'bg-indigo'}`} role="status">{a.note}</div>}
      {(a.status === 'open' || a.status === 'checking') && (
        <>
          {isPay && a.status === 'open' && <div className="note bg-hold">Payment held until you decide.</div>}
          {confirming ? (
            <div className="note bg-check" role="alert">
              Only release it if you have confirmed the bank details with {a.supplier_id ? 'the supplier on the number on file' : 'the person involved'}.
              <div className="decide" style={{ marginTop: 10 }}>
                <button className="btn clear" disabled={busy} onClick={() => decide('clear')}>Yes, I confirmed. Release it</button>
                <button className="btn plain" onClick={() => setConfirming(false)}>Cancel</button>
              </div>
            </div>
          ) : (
            <div className="decide">
              <button className="btn clear" disabled={busy} onClick={() => (isPay ? setConfirming(true) : decide('clear'))}>{L.clear}</button>
              <button className="btn check" disabled={busy || a.status === 'checking'} onClick={() => decide('check')}>{L.check}</button>
              <button className="btn hold" disabled={busy} onClick={() => decide('hold')}><Icon name="stop" size={16} /> {L.hold}</button>
            </div>
          )}
        </>
      )}
    </section>
  )
}

function ScoreBar({ score, t = { check: 3.5, hold: 6 } }) {
  const pct = (v) => `${(Math.min(v, 10) / 10) * 100}%`
  const color = score >= t.hold ? '#E5484D' : score >= t.check ? '#F5A524' : '#3CCB7F'
  return (
    <div style={{ marginTop: 8 }}>
      <div className="row" style={{ fontSize: 13 }}><b>Risk score {score}/10</b><span className="who">Check at {t.check} · Hold at {t.hold}</span></div>
      <div className="scorebar" aria-hidden="true">
        <div style={{ width: pct(score), background: color }} />
        <span style={{ left: pct(t.check) }} /><span style={{ left: pct(t.hold) }} />
      </div>
    </div>
  )
}

function Learned({ s }) {
  const [p, setP] = useState(null)
  const n = s.events.length
  useEffect(() => { api.profiles().then(setP).catch(() => {}) }, [n])
  if (!p) return <Panel><p className="empty">Loading what Shamar has learned…</p></Panel>
  return (
    <>
      <div className="grid2 even">
        {p.people.map((a) => (
          <Panel key={a.id} title={`${a.name}'s normal pattern`} sub={`From ${a.days} days of history`}
            action={<span className={`av ${avClass(a.kind, a.id)}`}>{a.name[0]}</span>}>
            <div className="facts">
              <span><small>Usually works</small><b>{a.hours}</b></span>
              <span><small>Role</small><b>{a.role}</b></span>
            </div>
            {a.habits.map((h) => {
              const rare = h.hi === 0
              const max = Math.max(h.hi * 1.4, h.today * 1.1, 4)
              return (
                <div key={h.label} className="habit">
                  <div className="row"><b>{h.label}</b>
                    <span className="who">{rare ? `rare: about ${h.per_month} a month` : `usually ${h.lo}–${h.hi} a day · expected today ~${Math.round(h.expected_day)}`} · today <strong style={{ color: h.status === 'above' ? 'var(--hold)' : 'var(--clear)' }}>{h.today}</strong></span>
                  </div>
                  {!rare && (
                    <div className="bar" aria-hidden="true">
                      <div className="band" style={{ left: `${(h.lo / max) * 100}%`, width: `${((h.hi - h.lo) / max) * 100}%` }} />
                      <div className="dot" style={{ left: `${Math.min(100, (h.today / max) * 100)}%`, borderColor: h.status === 'above' ? '#E5484D' : '#3CCB7F' }} />
                    </div>
                  )}
                </div>
              )
            })}
            {a.never.length > 0 && (
              <div><small className="who">Has never done (doing it would raise a flag)</small>
                <div className="tags" style={{ marginTop: 6 }}>{a.never.map((x) => <span key={x} className="pill muted">{x}</span>)}</div>
              </div>
            )}
          </Panel>
        ))}
      </div>
      <Panel title="Suppliers">
        <div className="tblwrap">
          <table className="tbl">
            <thead><tr><th>Supplier</th><th className="num">Past payments</th><th className="num">Usual amount</th><th>Shamar predicts next payment</th><th>Bank details</th><th>Status</th></tr></thead>
            <tbody>
              {p.suppliers.map((x) => (
                <tr key={x.id}>
                  <td><b>{x.name}</b></td>
                  <td className="num">{x.payments}</td>
                  <td className="num">{x.usual ? `${rand(x.usual[0])}–${rand(x.usual[1])}` : '–'}</td>
                  <td>{x.forecast ? <><b>{new Date(x.forecast.next + 'T12:00').toLocaleDateString('en-ZA', { weekday: 'short', day: 'numeric', month: 'short' })}</b> · about {rand(x.forecast.amount)}<small className="block">paid every {Math.round(x.forecast.every_days)} days</small></> : '–'}</td>
                  <td className="muted">{x.bank}</td>
                  <td><span className={`pill ${x.trust === 'unconfirmed' ? 'check' : x.trust === 'restored' ? 'indigo' : 'clear'}`}>{x.trust === 'unconfirmed' ? 'Unconfirmed change' : x.trust === 'restored' ? 'Restored' : 'Confirmed'}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  )
}

function downloadCsv(rows, day) {
  const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`
  const lines = [['Date', 'Time', 'Who', 'Action', 'System', 'Risk score', 'Shamar decision', 'Result', 'Reasons'].map(esc).join(',')]
  rows.slice().reverse().forEach((e) => lines.push([day, e.time, e.actor, e.summary, e.system, e.score || 0, e.level,
    OUTCOME[e.outcome]?.text || e.outcome, (e.reasons || []).map((r) => r.text).join(' | ')].map(esc).join(',')))
  const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv' }))
  const link = document.createElement('a')
  link.href = url; link.download = `shamar-audit-log-${day}.csv`; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

const LEVELS = [
  { id: 'relaxed', name: 'Relaxed', text: 'Fewer alerts. Only clear risks are held.', t: 'Check at 4.5 · Hold at 7' },
  { id: 'balanced', name: 'Balanced', text: 'Recommended for most small businesses.', t: 'Check at 3.5 · Hold at 6' },
  { id: 'strict', name: 'Strict', text: 'More alerts. Use after a fraud attempt or in busy season.', t: 'Check at 2.5 · Hold at 5' },
]

function SettingsPage({ toast, refresh }) {
  const [f, setF] = useState(null)
  const [saving, setSaving] = useState(false)
  useEffect(() => { api.getSettings().then(setF) }, [])
  if (!f) return <Panel><p className="empty">Loading settings…</p></Panel>
  const save = async (e) => {
    e.preventDefault(); setSaving(true)
    try { setF(await api.saveSettings({ sensitivity: f.sensitivity, payment_limit: Number(f.payment_limit) || 0, pause_ai: f.pause_ai })); toast('Settings saved'); refresh() }
    catch (err) { toast(err.message) } finally { setSaving(false) }
  }
  return (
    <form onSubmit={save} className="split rev">
      <Panel title="How strict should Shamar be?">
        <div className="levels" role="radiogroup" aria-label="Sensitivity">
          {LEVELS.map((l) => (
            <label key={l.id} className={`level ${f.sensitivity === l.id ? 'on' : ''}`}>
              <input type="radio" name="sens" value={l.id} checked={f.sensitivity === l.id} onChange={() => setF({ ...f, sensitivity: l.id })} />
              <span><b>{l.name}</b><small>{l.text}</small><small className="muted">{l.t}</small></span>
            </label>
          ))}
        </div>
      </Panel>
      <Panel title="Payments and AI">
        <label>Hold any single payment above (R)
          <input inputMode="numeric" value={f.payment_limit} onChange={(e) => setF({ ...f, payment_limit: e.target.value.replace(/\D/g, '') })} />
          
        </label>
        <label className="toggle">
          <input type="checkbox" checked={f.pause_ai} onChange={(e) => setF({ ...f, pause_ai: e.target.checked })} />
          <span><b>Pause the AI assistant when Shamar stops it</b></span>
        </label>
        <button className="btn primary" type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save settings'}</button>
        <button type="button" className="btn soft" onClick={async () => { await api.reset(); toast('Data reset to 08:00'); refresh() }}>Reset all data to 08:00</button>
      </Panel>
    </form>
  )
}

function Forecast({ s, onMore }) {
  const [p, setP] = useState(null)
  const n = s.events.length
  useEffect(() => { api.profiles().then(setP).catch(() => {}) }, [n, s.clock])
  if (!p) return null
  const rows = p.people.flatMap((a) => a.habits.map((h) => ({ who: a.name, kind: a.kind, id: a.id, ...h })))
  const upcoming = p.suppliers.filter((x) => x.forecast).sort((a, b) => a.forecast.next.localeCompare(b.forecast.next))
  const day = (d) => new Date(d + 'T12:00').toLocaleDateString('en-ZA', { weekday: 'short', day: 'numeric', month: 'short' })
  return (
    <div className="grid2">
      <Panel title="Shamar's forecast for today"
        action={<button className="btn soft small" onClick={onMore}>See patterns</button>}>
        <div className="tblwrap">
          <table className="tbl">
            <thead><tr><th>Who</th><th>Activity</th><th className="num">So far</th><th>Prediction</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.who + r.label}>
                  <td><span className="who2"><span className={`av sm ${avClass(r.kind, r.id)}`}>{r.who[0]}</span>{r.who}</span></td>
                  <td>{r.label}</td>
                  <td className="num">{r.today}</td>
                  <td><span className={r.trend === 'above' ? 'fc above' : 'fc'}>{r.forecast}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <Panel title="Expected supplier payments">
        <ul className="teamlist">
          {upcoming.map((x) => (
            <li key={x.id}>
              <span className="av sm person">{x.name[0]}</span>
              <span className="what"><b>{x.name}</b><small>Every ~{Math.round(x.forecast.every_days)} days · usually {rand(x.forecast.amount)}</small></span>
              <span className="pill muted">{day(x.forecast.next)}</span>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  )
}
