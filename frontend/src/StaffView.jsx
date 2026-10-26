import { useEffect, useState } from 'react'
import { api } from './api.js'
import { OUTCOME, ShamarResult } from './App.jsx'
import { Kpi, Panel, Shell, avClass, rand } from './ui.jsx'

const PAY_PILL = {
  held: { text: 'Held by Shamar', cls: 'hold' },
  awaiting_owner: { text: 'With Thandi', cls: 'muted' },
  paid: { text: 'Paid', cls: 'clear' },
  blocked: { text: 'Blocked', cls: 'indigo' },
}

export default function StaffView({ s, refresh, toast, shell }) {
  const [page, setPage] = useState('overview')
  const [openMail, setOpenMail] = useState(null)
  const lindi = s.actors.find((a) => a.id === 'lindi')
  const mine = s.events.filter((e) => e.actor_id === 'sipho')
  const myPays = s.payments.filter((p) => p.prepared_by === 'sipho')
  const waiting = s.queries.filter((q) => q.status === 'new').length
  const answered = s.queries.filter((q) => q.status === 'answered').length
  const unread = s.inbox.filter((m) => !s.events.some((e) => e.action === 'read_email' && e.params?.email_id === m.id)).length
  const nav = [
    { id: 'overview', label: 'Overview', icon: 'home' },
    { id: 'inbox', label: 'Inbox', icon: 'mail', badge: unread || null },
    { id: 'payments', label: 'Supplier payments', icon: 'card' },
    { id: 'chats', label: 'Customer chats', icon: 'chat', badge: waiting || null },
    { id: 'activity', label: 'My activity', icon: 'list' },
  ]
  const titles = { overview: 'Good morning, Sipho', inbox: 'Inbox', payments: 'Supplier payments', chats: 'Customer chats (Lindi)', activity: 'My activity' }
  const goMail = (id) => { setOpenMail(id); setPage('inbox') }

  return (
    <Shell {...shell} nav={nav} page={page} setPage={setPage} title={titles[page]} clock={s.clock} day={s.day}>
      {page === 'overview' && (
        <>
          <div className="kpis">
            <Kpi icon="chat" label="Customers answered by Lindi" value={answered} sub={lindi.paused ? 'Lindi is paused' : `${waiting} waiting`} tone={lindi.paused ? 'hold' : ''} />
            <Kpi icon="mail" label="Unread emails" value={unread} sub={`${s.inbox.length} in inbox`} />
            <Kpi icon="card" label="Payments I prepared" value={myPays.length} sub={rand(myPays.reduce((t, p) => t + p.amount, 0))} />
            <Kpi icon="shield" label="Held by Shamar" value={myPays.filter((p) => p.status === 'held').length} tone={myPays.some((p) => p.status === 'held') ? 'hold' : 'clear'} sub="waiting for Thandi" />
          </div>
          <div className="grid2">
            <Panel title="Inbox" action={<button className="btn soft small" onClick={() => setPage('inbox')}>Open inbox</button>}>
              <ul className="maillist">
                {s.inbox.slice(0, 5).map((m) => (
                  <li key={m.id}><button onClick={() => goMail(m.id)}><span className="av sm person">{m.from_name[0]}</span><span className="what"><b>{m.from_name}</b><small>{m.subject}</small></span><span className="muted">{m.ts.slice(11, 16)}</span></button></li>
                ))}
              </ul>
            </Panel>
            <Panel title="Lindi, AI assistant" action={lindi.paused ? <span className="pill hold">Paused</span> : <span className="pill clear">Working</span>}>
              <LindiSummary s={s} />
              <button className="btn soft" onClick={() => setPage('chats')}>Open customer chats</button>
            </Panel>
          </div>
          <Panel title="My recent activity">
            <ActivityTable rows={mine.slice(0, 6)} />
          </Panel>
        </>
      )}
      {page === 'inbox' && <Inbox s={s} refresh={refresh} openId={openMail} setOpenId={setOpenMail} goPay={() => setPage('payments')} />}
      {page === 'payments' && (
        <div className="split rev">
          <PayForm s={s} refresh={refresh} />
          <Panel title="My payments today">
            <div className="tblwrap">
              <table className="tbl">
                <thead><tr><th>Time</th><th>Supplier</th><th>Account</th><th className="num">Amount</th><th>Status</th></tr></thead>
                <tbody>
                  {myPays.length === 0 && <tr><td colSpan={5} className="empty">No payments yet today.</td></tr>}
                  {myPays.map((p) => (
                    <tr key={p.id}><td className="muted">{p.ts.slice(11, 16)}</td><td><b>{p.supplier}</b></td><td className="mono">{p.account}</td><td className="num"><b>{rand(p.amount)}</b></td><td><span className={`pill ${PAY_PILL[p.status].cls}`}>{PAY_PILL[p.status].text}</span></td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            <h3 style={{ marginTop: 8 }}>Suppliers</h3>
            <div className="tblwrap">
              <table className="tbl">
                <thead><tr><th>Supplier</th><th>Bank</th><th>Account on file</th><th>Phone on file</th></tr></thead>
                <tbody>
                  {s.suppliers.map((x) => (
                    <tr key={x.id}><td><b>{x.name}</b></td><td>{x.bank_name}</td><td className="mono">{x.account} {x.changed_today && <span className="pill check">changed today</span>}</td><td className="muted">{x.verified_phone}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>
      )}
      {page === 'chats' && <LindiPanel s={s} lindi={lindi} refresh={refresh} toast={toast} />}
      {page === 'activity' && <Panel title="Everything I did today"><ActivityTable rows={mine} /></Panel>}
    </Shell>
  )
}

function ActivityTable({ rows }) {
  return (
    <div className="tblwrap">
      <table className="tbl">
        <thead><tr><th>Time</th><th>Action</th><th>System</th><th className="num">Risk</th><th>Result</th></tr></thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={5} className="empty">Nothing yet today.</td></tr>}
          {rows.map((e) => (
            <tr key={e.id}><td className="muted">{e.time}</td><td>{e.summary}</td><td className="muted">{e.system}</td><td className="num">{e.score || '–'}</td><td><span className={`pill ${OUTCOME[e.outcome].cls}`}>{OUTCOME[e.outcome].text}</span></td></tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function LindiSummary({ s }) {
  const recent = s.queries.filter((q) => q.status !== 'new').slice(-3).reverse()
  if (!recent.length) return <p className="empty">No customer chats yet.</p>
  return (
    <ul className="maillist">
      {recent.map((q) => (
        <li key={q.id}><div><span className="av sm ai">L</span><span className="what"><b>{q.customer}</b><small>{q.status === 'blocked' ? 'Stopped by Shamar' : q.reply}</small></span><span className={`pill ${q.status === 'blocked' ? 'hold' : 'clear'}`}>{q.status === 'blocked' ? 'Stopped' : 'Answered'}</span></div></li>
      ))}
    </ul>
  )
}

function LindiPanel({ s, lindi, refresh, toast }) {
  const [busy, setBusy] = useState(false)
  const next = async () => {
    setBusy(true)
    try {
      const r = await api.lindiNext()
      if (r.done || r.paused) toast(r.message)
      else if (r.tricked) toast('Shamar stopped Lindi')
      await refresh()
    } finally { setBusy(false) }
  }
  const waiting = s.queries.filter((q) => q.status === 'new').length
  const evById = Object.fromEntries(s.events.map((e) => [e.id, e]))
  return (
    <Panel title="Lindi's conversations"
      action={lindi.paused ? <span className="pill hold">Paused by Thandi</span> : <span className="pill clear">Working</span>}>
      <div className="chat">
        {s.queries.filter((q) => q.status !== 'new').map((q) => {
          const ev = evById[q.event_id]
          return (
            <div className="msg" key={q.id}>
              <span className="who">{q.customer} · {q.email}</span>
              <div className="bubble them">{q.text}</div>
              {q.status === 'answered' && <div className="bubble lindi">{q.reply}</div>}
              {q.status === 'blocked' && (
                <div className="bubble stopped">Lindi {ev?.summary?.replace(/^Tried/, 'tried')}. {ev?.outcome === 'denied' ? 'Not allowed.' : 'Shamar stopped it.'}</div>
              )}
              {ev && <span className="who" style={{ alignSelf: 'flex-end' }}>{ev.outcome === 'denied' ? 'Permission: not allowed' : `Shamar: ${ev.level === 'clear' ? 'Clear' : ev.level === 'check' ? 'Check' : 'Hold'} · ${ev.score}/10`}</span>}
            </div>
          )
        })}
        {waiting > 0 && <p className="empty">{waiting} customer {waiting === 1 ? 'question' : 'questions'} waiting</p>}
      </div>
      <button className="btn soft" onClick={next} disabled={busy || waiting === 0 || !!lindi.paused}>
        {lindi.paused ? 'Lindi is paused by Thandi' : waiting === 0 ? 'All customers answered' : 'Let Lindi answer the next one'}
      </button>
    </Panel>
  )
}

function Inbox({ s, refresh, openId, setOpenId, goPay }) {
  const [result, setResult] = useState(null)
  const [form, setForm] = useState(null)
  const mail = s.inbox.find((m) => m.id === openId)
  const read = new Set(s.events.filter((e) => e.action === 'read_email').map((e) => e.params?.email_id))

  useEffect(() => {
    if (openId && !read.has(openId)) api.readEmail(openId).then(refresh)
  }, [openId]) // eslint-disable-line react-hooks/exhaustive-deps

  const open = (m) => { setOpenId(m.id); setResult(null); setForm(null) }
  const startUpdate = () => setForm({ new_account: mail.ask.new_account, bank_name: mail.ask.bank_name })
  const save = async (e) => {
    e.preventDefault()
    try {
      const r = await api.changeBank(mail.ask.supplier_id, { ...form, source_email_id: mail.id })
      setResult(r); setForm(null); refresh()
    } catch (err) { setResult({ level: 'hold', score: '-', message: err.message, reasons: [] }) }
  }
  const supplier = mail?.ask?.supplier_id && s.suppliers.find((x) => x.id === mail.ask.supplier_id)
  const [popResult, setPopResult] = useState(null)
  const [sum, setSum] = useState(null)
  const [summing, setSumming] = useState(false)
  useEffect(() => { setPopResult(null); setSum(null) }, [openId])
  const summarise = async () => {
    setSumming(true)
    try { setSum(await api.summarise(mail.id)); refresh() }
    catch (err) { setSum({ level: 'hold', score: '-', message: err.message, reasons: [] }) }
    finally { setSumming(false) }
  }
  const releaseOrder = async () => {
    try { setPopResult(await api.releaseOrder(mail.id)); refresh() }
    catch (err) { setPopResult({ level: 'hold', score: '-', message: err.message, reasons: [] }) }
  }
  const [np, setNp] = useState(null)
  const [npResult, setNpResult] = useState(null)
  useEffect(() => { setNp(null); setNpResult(null) }, [openId])
  const startNew = () => setNp({ name: mail.ask.supplier_name, bank_name: mail.ask.bank_name, account: mail.ask.account, amount: String(mail.ask.amount) })
  const saveNew = async (e) => {
    e.preventDefault()
    try {
      const r = await api.newSupplierPay({ ...np, amount: Number(np.amount), source_email_id: mail.id })
      setNpResult(r); setNp(null); refresh()
    } catch (err) { setNpResult({ supplier: { level: 'hold', score: '-', message: err.message, reasons: [] } }) }
  }

  return (
    <div className="mailclient">
      <Panel title="Inbox" className="maillistpanel">
        <ul className="maillist">
          {s.inbox.map((m) => (
            <li key={m.id}>
              <button className={`${m.id === openId ? 'on' : ''} ${read.has(m.id) ? '' : 'unread'}`} onClick={() => open(m)}>
                <span className={`av sm ${avClass(null, 'x')}`}>{m.from_name[0]}</span>
                <span className="what"><b>{m.from_name}</b><small>{m.subject}</small></span>
                <span className="muted">{m.ts.slice(11, 16)}</span>
              </button>
            </li>
          ))}
        </ul>
      </Panel>
      <Panel className="reading">
        {!mail ? <p className="empty">Choose an email to read it.</p> : (
          <>
            <div>
              <h2 style={{ fontSize: 20 }}>{mail.subject}</h2>
              <div className="from">From <b>{mail.from_name}</b> <code>{mail.from_addr}</code> · {mail.ts.slice(11, 16)}</div>
            </div>
            <div className="mailbody">{mail.body}</div>
            {!sum && <button className="btn soft" style={{ alignSelf: 'flex-start' }} onClick={summarise} disabled={summing}>Ask Lindi to summarise</button>}
            {sum?.summary && (
              <div className="note" style={{ background: 'var(--indigo-soft)' }}><b>Lindi's summary</b><br />{sum.summary}</div>
            )}
            {sum && !sum.summary && <ShamarResult r={sum} />}
            {sum?.hidden && sum.level !== 'clear' && (
              <div className="hiddentext">
                <b>Hidden in this email (invisible to you, but not to the AI)</b>
                <p>{sum.hidden}</p>
              </div>
            )}
            {mail.ask?.type === 'bank_change' && !mail.done && !form && !result && (
              <button className="btn primary" onClick={startUpdate}>Update {supplier?.name} bank details</button>
            )}
            {form && (
              <form className="grid" onSubmit={save}>
                <label className="full">Supplier<input value={supplier?.name || ''} readOnly /></label>
                <label>New account number
                  <input inputMode="numeric" value={form.new_account} onChange={(e) => setForm({ ...form, new_account: e.target.value.replace(/\D/g, '') })} required />
                </label>
                <label>Bank<input value={form.bank_name} onChange={(e) => setForm({ ...form, bank_name: e.target.value })} required /></label>
                <button className="btn primary full" type="submit">Save new details</button>
              </form>
            )}
            <ShamarResult r={result} />
            {result && result.outcome !== 'blocked' && <button className="btn soft" onClick={goPay}>Go to supplier payments</button>}
            {mail.ask?.type === 'pop_release' && !mail.done && !popResult && (
              <button className="btn primary" onClick={releaseOrder}>Mark order #{mail.ask.order} as paid and release it</button>
            )}
            {popResult && <ShamarResult r={popResult} />}
            {mail.ask?.type === 'new_supplier_payment' && !mail.done && !np && !npResult && (
              <button className="btn primary" onClick={startNew}>Add {mail.ask.supplier_name} and pay R{Number(mail.ask.amount).toLocaleString('en-ZA').replace(/\s/g, ',')}</button>
            )}
            {np && (
              <form className="grid" onSubmit={saveNew}>
                <label className="full">New supplier<input value={np.name} onChange={(e) => setNp({ ...np, name: e.target.value })} required /></label>
                <label>Bank<input value={np.bank_name} onChange={(e) => setNp({ ...np, bank_name: e.target.value })} required /></label>
                <label>Account number<input inputMode="numeric" value={np.account} onChange={(e) => setNp({ ...np, account: e.target.value.replace(/\D/g, '') })} required /></label>
                <label className="full">Amount (R)<input inputMode="decimal" value={np.amount} onChange={(e) => setNp({ ...np, amount: e.target.value.replace(/[^\d.]/g, '') })} required /></label>
                <button className="btn primary full" type="submit">Add supplier and prepare payment</button>
              </form>
            )}
            {npResult && (
              <>
                {npResult.supplier && npResult.payment && (
                  <div className={`note bg-${npResult.supplier.level}`}>Supplier: {npResult.supplier.message} (Shamar {npResult.supplier.score}/10)</div>
                )}
                <ShamarResult r={npResult.payment || npResult.supplier} />
              </>
            )}
          </>
        )}
      </Panel>
    </div>
  )
}

function PayForm({ s, refresh }) {
  const [f, setF] = useState({ supplier_id: 'mzansi', amount: '48600', reference: 'INV-2291' })
  const [result, setResult] = useState(null)
  const sup = s.suppliers.find((x) => x.id === f.supplier_id)
  useEffect(() => { setResult(null) }, [f.supplier_id])
  const submit = async (e) => {
    e.preventDefault()
    try {
      const r = await api.pay({ ...f, amount: Number(f.amount) })
      setResult(r); refresh()
    } catch (err) { setResult({ level: 'hold', score: '-', message: err.message, reasons: [] }) }
  }
  return (
    <Panel title="Pay a supplier">
      <form className="grid" onSubmit={submit}>
        <label className="full">Supplier
          <select value={f.supplier_id} onChange={(e) => setF({ ...f, supplier_id: e.target.value })}>
            {s.suppliers.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select>
        </label>
        <div className="full from">Paying account on file <code>{sup?.account}</code>{sup?.changed_today && <span className="pill check" style={{ marginLeft: 8 }}>changed today</span>}</div>
        <label>Amount (R)<input inputMode="decimal" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value.replace(/[^\d.]/g, '') })} required /></label>
        <label>Reference<input value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} maxLength={40} /></label>
        <button className="btn primary full" type="submit">Prepare payment</button>
      </form>
      <ShamarResult r={result} />
    </Panel>
  )
}
