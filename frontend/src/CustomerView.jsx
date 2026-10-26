import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import { Icon } from './ui.jsx'

const SUGGESTED = [
  'Do you have the blue shweshwe dress in size M?',
  'Do you deliver to Soweto?',
  'Can I return something I bought?',
]

export default function CustomerView({ toast, onSwitch }) {
  const [me, setMe] = useState({ name: '', email: '' })
  const [chat, setChat] = useState({ messages: [], lindi_paused: false })
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const ready = me.name.trim() && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(me.email)

  const load = useCallback(() => {
    if (!ready) return
    api.chat(me.email).then(setChat).catch(() => {})
  }, [me.email, ready])
  useEffect(() => { load(); const t = setInterval(load, 2000); return () => clearInterval(t) }, [load])

  const send = async (msg) => {
    const body = (msg ?? text).trim()
    if (!body || !ready) return
    setBusy(true)
    try { await api.ask({ ...me, text: body }); setText(''); await load() }
    catch (e) { toast(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="shop">
      <header className="shopbar">
        <div className="shopbrand"><Icon name="bag" size={22} />Thandi's Boutique</div>
        <nav className="shopnav" aria-label="Shop"><span>New in</span><span>Dresses</span><span>Sandals</span><span>Delivery</span></nav>
        <div className="shopstaff"><button className="link" onClick={() => onSwitch('sipho')}>Staff sign in</button></div>
      </header>
      <section className="shophero">
        <div>
          <h1>Shweshwe, made for you.</h1>
          <p>Shop 12, Maponya Mall, Soweto · Mon–Fri 08:00–17:00 · Sat 09:00–15:00</p>
        </div>
      </section>
      <div className="cols shopcols">
        <div className="col wide">
          <section className="panel">
            <div className="row">
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <span className="av ai">L</span>
                <div style={{ lineHeight: 1.25 }}><h2>Chat with Lindi</h2><span className="who">Our assistant</span></div>
              </div>
              {chat.lindi_paused ? <span className="pill muted">Away</span> : <span className="pill clear">Online</span>}
            </div>
            {!ready && (
              <div className="grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <label>Your name<input value={me.name} maxLength={60} onChange={(e) => setMe({ ...me, name: e.target.value })} /></label>
                <label>Your email<input type="email" value={me.email} maxLength={120} onChange={(e) => setMe({ ...me, email: e.target.value })} /></label>
              </div>
            )}
            {ready && <div className="who">Chatting as {me.name} · <button className="link" onClick={() => setMe({ name: '', email: '' })}>change</button></div>}
            <div className="chat" aria-live="polite">
              {ready && chat.messages.length === 0 && <p className="empty">Hi! How can we help?</p>}
              {chat.messages.map((m) => (
                <div className="msg" key={m.id}>
                  <div className="bubble lindi" style={{ alignSelf: 'flex-end', background: 'var(--soft)' }}>{m.text}</div>
                  {m.status === 'answered' && <div className="bubble them" style={{ background: 'var(--indigo-soft)' }}>{m.reply}</div>}
                  {m.status !== 'answered' && <div className="bubble them" style={{ background: 'var(--indigo-soft)' }}>Thanks for your message. A team member will get back to you shortly.</div>}
                </div>
              ))}
            </div>
            <form onSubmit={(e) => { e.preventDefault(); send() }} style={{ display: 'flex', gap: 10 }}>
              <label className="sr" htmlFor="msg">Message</label>
              <input id="msg" value={text} maxLength={1000} placeholder={ready ? 'Type a message…' : 'Enter your name and email first'} disabled={!ready} onChange={(e) => setText(e.target.value)} />
              <button className="btn primary" type="submit" disabled={busy || !ready || !text.trim()}>Send</button>
            </form>
            {ready && (
              <div className="tags">
                {SUGGESTED.map((q) => <button key={q} className="chip" onClick={() => send(q)} disabled={busy}>{q}</button>)}
              </div>
            )}
          </section>
        </div>
        <div className="col">
          <ContactForm toast={toast} />
        </div>
      </div>
    </div>
  )
}

function ContactForm({ toast }) {
  const empty = { from_name: '', from_addr: '', subject: '', body: '' }
  const [f, setF] = useState(empty)
  const [sent, setSent] = useState(false)
  const submit = async (e) => {
    e.preventDefault()
    try { await api.emailShop(f); setF(empty); setSent(true) } catch (err) { toast(err.message) }
  }
  return (
    <section className="panel">
      <h2>Contact us</h2>
      <form className="grid" onSubmit={submit}>
        <label>Name<input value={f.from_name} maxLength={80} onChange={(e) => setF({ ...f, from_name: e.target.value })} required /></label>
        <label>Email<input type="email" value={f.from_addr} maxLength={120} onChange={(e) => setF({ ...f, from_addr: e.target.value })} required /></label>
        <label className="full">Subject<input value={f.subject} maxLength={120} onChange={(e) => setF({ ...f, subject: e.target.value })} required /></label>
        <label className="full">Message
          <textarea rows={6} value={f.body} maxLength={3000} onChange={(e) => setF({ ...f, body: e.target.value })} required />
        </label>
        <button className="btn primary full" type="submit">Send</button>
      </form>
      {sent && <div className="note bg-clear" role="status">Thanks, your message was sent.</div>}
    </section>
  )
}
