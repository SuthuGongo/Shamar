const tokens = {}
try { Object.assign(tokens, JSON.parse(sessionStorage.getItem('shamar-tokens') || '{}')) } catch { /* private mode */ }

export function setToken(role, token) {
  tokens[role] = token
  try { sessionStorage.setItem('shamar-tokens', JSON.stringify(tokens)) } catch { /* ignore */ }
}
export const hasToken = (role) => !!tokens[role]

async function call(method, path, role, body) {
  const res = await fetch(`/api${path}`, {
    method,
    headers: { 'Content-Type': 'application/json', ...(role && tokens[role] ? { Authorization: `Bearer ${tokens[role]}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    if (res.status === 401 && role) setToken(role, null)
    const detail = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join(', ') : data.detail
    const err = new Error(detail || `Request failed (${res.status})`)
    err.status = res.status
    throw err
  }
  return data
}

export const api = {
  login: (email, password) => call('POST', '/login', null, { email, password }),
  demoAccounts: () => call('GET', '/demo-accounts'),
  state: (role) => call('GET', '/state', role),
  reset: () => call('POST', '/reset'),
  // customer (public)
  ask: (body) => call('POST', '/shop/ask', null, body),
  chat: (email) => call('GET', `/shop/chat?email=${encodeURIComponent(email)}`),
  emailShop: (body) => call('POST', '/shop/email', null, body),
  // Sipho
  lindiNext: () => call('POST', '/lindi/next', 'sipho'),
  readEmail: (id) => call('POST', `/inbox/${id}/read`, 'sipho'),
  summarise: (id) => call('POST', `/inbox/${id}/summarise`, 'sipho'),
  changeBank: (supplierId, body) => call('POST', `/suppliers/${supplierId}/bank`, 'sipho', body),
  pay: (body) => call('POST', '/payments', 'sipho', body),
  releaseOrder: (emailId) => call('POST', '/orders/release', 'sipho', { email_id: emailId }),
  newSupplierPay: (body) => call('POST', '/suppliers/new-and-pay', 'sipho', body),
  // Thandi
  approve: (id) => call('POST', `/payments/${id}/approve`, 'thandi'),
  decide: (id, decision) => call('POST', `/alerts/${id}/decision`, 'thandi', { decision }),
  profiles: () => call('GET', '/profiles', 'thandi'),
  getSettings: () => call('GET', '/settings', 'thandi'),
  saveSettings: (body) => call('PUT', '/settings', 'thandi', body),
  resume: (actorId) => call('POST', `/actors/${actorId}/resume`, 'thandi'),
}
