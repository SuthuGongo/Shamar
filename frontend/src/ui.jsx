import { useState } from 'react'
import {
  ArcElement, BarElement, CategoryScale, Chart as ChartJS, Legend, LinearScale, Tooltip,
} from 'chart.js'
import { Bar, Doughnut } from 'react-chartjs-2'

ChartJS.register(ArcElement, BarElement, CategoryScale, LinearScale, Tooltip, Legend)
ChartJS.defaults.font.family = "Inter, system-ui, sans-serif"
ChartJS.defaults.color = '#6B7280'

const PATHS = {
  home: 'M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z',
  bell: 'M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10 21h4',
  card: 'M3 6h18v12H3zM3 10h18M7 15h4',
  list: 'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01',
  users: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75',
  mail: 'M3 5h18v14H3zM3 6l9 7 9-7',
  chat: 'M21 12a8 8 0 0 1-11.6 7.1L3 21l1.9-6.4A8 8 0 1 1 21 12z',
  shield: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  stop: 'M8 3h8l5 5v8l-5 5H8l-5-5V8zM9 9l6 6M15 9l-6 6',
  logout: 'M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9',
  refresh: 'M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5',
  money: 'M3 6h18v12H3zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6',
  bag: 'M5 8h14l-1 13H6zM9 8V6a3 3 0 0 1 6 0v2',
}

export function Icon({ name, size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={PATHS[name]} /></svg>
  )
}

export function Logo({ size = 32 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="#3B44C4" />
      <path d="M16 5.5l8.5 3.2v6.6c0 5.6-3.7 9.6-8.5 11.2-4.8-1.6-8.5-5.6-8.5-11.2V8.7z" fill="#fff" />
      <text x="16" y="21" textAnchor="middle" fontFamily="Inter, system-ui, sans-serif" fontWeight="800" fontSize="13" fill="#3B44C4">S</text>
    </svg>
  )
}

export function Shell({ me, nav, page, setPage, title, clock, day, onLogout, onSwitch, onReset, children }) {
  const dayLabel = day ? new Date(day + 'T12:00').toLocaleDateString('en-ZA', { weekday: 'short', day: 'numeric', month: 'short' }) : ''
  return (
    <div className="app">
      <aside className="side">
        <div className="brand"><Logo />shamar</div>
        <div className="workspace">Thandi's Boutique</div>
        <nav aria-label="Main">
          {nav.map((n) => (
            <button key={n.id} className={`navi ${page === n.id ? 'on' : ''}`} onClick={() => setPage(n.id)} aria-current={page === n.id ? 'page' : undefined}>
              <Icon name={n.icon} /><span>{n.label}</span>{n.badge ? <span className="badge">{n.badge}</span> : null}
            </button>
          ))}
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          <div>
            <div className="crumb">{me.id === 'thandi' ? 'Owner' : 'Staff'} / {nav.find((n) => n.id === page)?.label}</div>
            <h1>{title}</h1>
          </div>
          <div className="topright">
            <span className="clock">{dayLabel} · {clock}</span>
            <span className="shield"><Icon name="shield" size={16} />Shamar on</span>
            <AccountMenu me={me} onSwitch={onSwitch} onLogout={onLogout} />
          </div>
        </header>
        <div className="content">{children}</div>
      </div>
    </div>
  )
}

function AccountMenu({ me, onSwitch, onLogout }) {
  const [open, setOpen] = useState(false)
  const other = me.id === 'thandi' ? { id: 'sipho', label: 'Sipho (Store admin)' } : { id: 'thandi', label: 'Thandi (Owner)' }
  return (
    <div className="acct">
      <button className="userchip" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className={`av ${me.kind === 'owner' ? 'owner' : 'person'}`}>{me.name[0]}</span><span><b>{me.name}</b><small>{me.role}</small></span>
      </button>
      {open && (
        <div className="menu" role="menu" onMouseLeave={() => setOpen(false)}>
          <button role="menuitem" onClick={() => { setOpen(false); onSwitch(other.id) }}>Switch to {other.label}</button>
          <button role="menuitem" onClick={() => { setOpen(false); onSwitch('customer') }}>View shop website</button>
          <button role="menuitem" onClick={() => { setOpen(false); onLogout() }}><Icon name="logout" size={15} /> Log out</button>
        </div>
      )}
    </div>
  )
}

export function Kpi({ icon, label, value, sub, tone }) {
  return (
    <div className={`kpi ${tone || ''}`}>
      <span className="kpiicon"><Icon name={icon} /></span>
      <div><span className="kpilabel">{label}</span><b>{value}</b>{sub && <small>{sub}</small>}</div>
    </div>
  )
}

export function Panel({ title, sub, action, children, className = '' }) {
  return (
    <section className={`panel ${className}`}>
      {(title || action) && (
        <div className="panelhead"><div><h2>{title}</h2>{sub && <p>{sub}</p>}</div>{action}</div>
      )}
      {children}
    </section>
  )
}

const TONE = { clear: '#3CCB7F', check: '#F5A524', hold: '#E5484D' }
const toneOf = (e) => (['held', 'blocked', 'denied', 'refused'].includes(e.outcome) ? 'hold' : e.outcome === 'flagged' ? 'check' : 'clear')

export function ActivityChart({ events }) {
  const hours = ['07', '08', '09', '10', '11', '12', '13', '14', '15', '16', '17']
  const count = (tone) => hours.map((h) => events.filter((e) => e.time.slice(0, 2) === h && toneOf(e) === tone).length)
  const data = {
    labels: hours.map((h) => `${h}:00`),
    datasets: [
      { label: 'Went through', data: count('clear'), backgroundColor: TONE.clear, borderRadius: 6, stack: 's' },
      { label: 'Flagged', data: count('check'), backgroundColor: TONE.check, borderRadius: 6, stack: 's' },
      { label: 'Stopped', data: count('hold'), backgroundColor: TONE.hold, borderRadius: 6, stack: 's' },
    ],
  }
  return (
    <div className="chartbox">
      <Bar data={data} options={{
        maintainAspectRatio: false, animation: false,
        plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, boxHeight: 10, useBorderRadius: true, borderRadius: 3 } } },
        scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, beginAtZero: true, ticks: { precision: 0 }, grid: { color: '#F1ECE5' } } },
      }} />
    </div>
  )
}

export function OutcomeDonut({ events }) {
  const n = (t) => events.filter((e) => toneOf(e) === t).length
  const total = events.length
  return (
    <div className="donutwrap">
      <div className="chartbox small">
        <Doughnut data={{
          labels: ['Went through', 'Flagged', 'Stopped'],
          datasets: [{ data: total ? [n('clear'), n('check'), n('hold')] : [1, 0, 0], backgroundColor: total ? [TONE.clear, TONE.check, TONE.hold] : ['#F1ECE5'], borderWidth: 0 }],
        }} options={{ cutout: '72%', animation: false, plugins: { legend: { display: false }, tooltip: { enabled: total > 0 } } }} />
        <div className="donutmid"><b>{total ? Math.round((n('clear') / total) * 100) : 0}%</b><small>went through</small></div>
      </div>
      <ul className="legend">
        <li><i style={{ background: TONE.clear }} />Went through <b>{n('clear')}</b></li>
        <li><i style={{ background: TONE.check }} />Flagged <b>{n('check')}</b></li>
        <li><i style={{ background: TONE.hold }} />Stopped <b>{n('hold')}</b></li>
      </ul>
    </div>
  )
}

export const rand = (n) => 'R' + Math.round(n).toLocaleString('en-ZA').replace(/\s/g, ',')
export const avClass = (kind, id) => (kind === 'ai_agent' || id === 'lindi' ? 'ai' : kind === 'owner' || id === 'thandi' ? 'owner' : 'person')
