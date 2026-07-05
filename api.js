// ── NextGen Arcade API Client v2 ─────────────────────────────────
const API_BASE = window.location.origin;

const ngApi = {
  async get(path) {
    try {
      const r = await fetch(API_BASE + path);
      if (!r.ok) throw new Error(r.status);
      return r.json();
    } catch(e) { return null; }
  },
  async post(path, data) {
    try {
      const r = await fetch(API_BASE + path, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
      });
      if (!r.ok) throw new Error(r.status);
      return r.json();
    } catch(e) { return null; }
  },
  async del(path) {
    try {
      const r = await fetch(API_BASE + path, {method:'DELETE'});
      return r.json();
    } catch(e) { return null; }
  },

  getStations:       ()      => ngApi.get('/api/stations'),
  getStation:        (sid)   => ngApi.get('/api/station/'+sid),
  bookStation:       (data)  => ngApi.post('/api/book', data),
  endSession:        (sid)   => ngApi.post('/api/end/'+sid, {}),
  approvePending:    (sid)   => ngApi.post('/api/approve/'+sid, {}),
  getSessions:       (f={})  => ngApi.get('/api/sessions?'+new URLSearchParams(f)),
  getPending:        ()      => ngApi.get('/api/pending'),
  addPending:        (data)  => ngApi.post('/api/pending', data),
  getGames:          ()      => ngApi.get('/api/games'),
  updateGames:       (games) => ngApi.post('/api/games', {games}),
  getSettings:       ()      => ngApi.get('/api/settings'),
  updateSettings:    (d)     => ngApi.post('/api/settings', d),
  getCustomers:      ()      => ngApi.get('/api/customers'),
  addCustomer:       (data)  => ngApi.post('/api/customers', data),
  delCustomer:       (cid)   => ngApi.del('/api/customers/'+cid),
  stkPush:           (p,a,n,b)=> ngApi.post('/api/stk',{phone:p,amount:a,name:n,breakdown:b}),
  getStats:          ()      => ngApi.get('/api/stats'),
  estimateCharge:    (game,dur)=> ngApi.post('/api/pricing/estimate',{game,duration:dur}),
  getIntegrityLog:   ()      => ngApi.get('/api/integrity/log'),
  verifyCheck:       (data)  => ngApi.post('/api/integrity/verify', data),
  getIntegSchedule:  (sid)   => ngApi.get('/api/integrity/schedule/'+sid),
};

window.ngApi = ngApi;
