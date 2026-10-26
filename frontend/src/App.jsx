import { useCallback, useEffect, useRef, useState } from 'react'
import { api, hasToken, setToken } from './api.js'
import StaffView from './StaffView.jsx'
import OwnerView from './OwnerView.jsx'
import CustomerView from './CustomerView.jsx'
import { Logo } from './ui.jsx'

const VIEWS = ['customer', 'sipho', 'thandi']

export default function App() {
  const [view, setView] = useState(() => VIEWS.find((v) => `#${v}` === location.hash) || 'customer')
  const [state, setState] = useState(null)
  const [, setAuthTick] = useState(0)
  const [toast, setToast] = useState('')
  const staff = view !== 'customer'
  const loggedIn = staff && hasToken(view)

  const refresh = useCallback(() => {
    if (!staff || !hasToken(view)) return Promise.resolve()
    return api.state(view).then(setState).catch((e) => { if (e.status === 401) setAuthTick((n) => n + 1) })
  }, [staff, view])

  useEffect(() => {
    setState(null)
    refresh()
    const t = setInterval(refresh, 1500)
    return () => clearInterval(t)
  }, [refresh, loggedIn])
  useEffect(() => { history.replaceState(null, '', `#${view}`) }, [view])
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(''), 4000)
    return () => clearTimeout(t)
  }, [toast])

  const reset = async () => { await api.reset(); await refresh(); setToast('Data reset to 08:00.') }
  const logout = () => { setToken(view, null); setState(null); setAuthTick((n) => n + 1) }
  const shell = state && { me: state.me, onLogout: logout, onSwitch: setView, onReset: reset }

  return (
    <>
      {view === 'customer' && <CustomerView toast={setToast} onSwitch={setView} />}
      {staff && !loggedIn && <Login role={view} onDone={() => setAuthTick((n) => n + 1)} onSwitch={setView} />}
      {staff && loggedIn && !state && <p className="empty" style={{ paddingTop: 80 }}>Connecting to Shamar…</p>}
      {view === 'sipho' && loggedIn && state && <StaffView s={state} refresh={refresh} toast={setToast} shell={shell} />}
      {view === 'thandi' && loggedIn && state && <OwnerView s={state} refresh={refresh} toast={setToast} shell={shell} />}
      {toast && <div className="toast" role="status">{toast}</div>}
    </>
  )
}

function Login({ role, onDone, onSwitch }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const submit = async (e) => {
    e.preventDefault(); setError('')
    try {
      const r = await api.login(email, password)
      setToken(r.user.id, r.token)
      if (r.user.id !== role) { onSwitch(r.user.id); return }
      onDone()
    } catch (err) { setError(err.message) }
  }
  return (
    <div className="loginpage">
      <div className="loginform">
        <form onSubmit={submit} className="panel" style={{ width: '100%', maxWidth: 380 }}>
          <div className="brand" style={{ justifyContent: 'center', marginBottom: 4 }}><Logo size={36} />shamar</div>
          <h2 style={{ fontSize: 20 }}>Sign in</h2>
          <label>Email<input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
          <label>Password<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
          {error && <div className="note bg-hold" role="alert">{error}</div>}
          <button className="btn primary" type="submit">Sign in</button>
          <button type="button" className="link" onClick={() => onSwitch('customer')}>Back to the shop website</button>
        </form>
      </div>
    </div>
  )
}

export const LEVEL_TEXT = { clear: 'Clear', check: 'Check', hold: 'Hold' }
export const OUTCOME = {
  done: { text: 'Went through', cls: 'clear' },
  flagged: { text: 'Flagged', cls: 'check' },
  held: { text: 'Held', cls: 'hold' },
  blocked: { text: 'Stopped', cls: 'hold' },
  denied: { text: 'Not allowed', cls: 'hold' },
  refused: { text: 'Refused', cls: 'hold' },
}

export function Verdict({ r, title }) {
  if (!r) return null
  const denied = r.outcome === 'denied'
  return (
    <div className={`verdict bg-${r.level}`} role="status">
      <div className="checks">
        {denied
          ? <span className="pill hold" style={{ background: '#fff' }}>Permission: not allowed</span>
          : <span className="pill clear">Permission: allowed</span>}
        {!denied && <span className={`pill ${r.level}`} style={{ background: '#fff' }}>Shamar: {LEVEL_TEXT[r.level]} · {r.score}/10</span>}
      </div>
      <b>{title || r.message}</b>
      {r.reasons?.length > 0 && r.reasons.map((x, i) => (
        <div className="reason" key={i}><span className={`kind ${x.kind}`}>{x.kind}</span><span>{x.text}</span></div>
      ))}
    </div>
  )
}

const STEPS = [
  { name: 'Watch', text: 'Is this normal for this person?' },
  { name: 'Connect', text: 'Does it fit with what happened before?' },
  { name: 'Decide', text: 'Clear, Check or Hold' },
]

export function ShamarResult({ r }) {
  const [step, setStep] = useState(3)
  const last = useRef(null)
  useEffect(() => {
    if (!r || r === last.current) return
    last.current = r
    setStep(0)
    const t = [1, 2, 3].map((n) => setTimeout(() => setStep(n), n * 450))
    return () => t.forEach(clearTimeout)
  }, [r])
  if (!r) return null
  if (step < 3 && r.outcome !== 'denied') {
    return (
      <div className="checking" role="status" aria-live="polite">
        <b>Shamar is checking…</b>
        {STEPS.map((x, i) => (
          <div key={x.name} className={`cstep ${i < step ? 'done' : i === step ? 'now' : ''}`}>
            <span className="cdot" />{x.name}<small>{x.text}</small>
          </div>
        ))}
      </div>
    )
  }
  return <Verdict r={r} />
}
