// NextGen Arcade API Client
(function(){
  const BASE = window.location.origin;
  const req = async (method, path, data) => {
    try {
      const opts = { method, headers: {'Content-Type':'application/json'} };
      if (data) opts.body = JSON.stringify(data);
      const r = await fetch(BASE + path, opts);
      if (!r.ok) throw new Error(r.status);
      return r.json();
    } catch(e) { console.warn('[API]', method, path, e.message); return null; }
  };
  window.ngApi = {
    getStations:      ()       => req('GET',  '/api/stations'),
    getStation:       (sid)    => req('GET',  '/api/station/'+sid),
    bookStation:      (d)      => req('POST', '/api/book', d),
    endSession:       (sid)    => req('POST', '/api/end/'+sid, {}),
    approvePending:   (sid)    => req('POST', '/api/approve/'+sid, {}),
    getSessions:      (f={})   => req('GET',  '/api/sessions?'+new URLSearchParams(f)),
    getPending:       ()       => req('GET',  '/api/pending'),
    addPending:       (d)      => req('POST', '/api/pending', d),
    getGames:         ()       => req('GET',  '/api/games'),
    updateGames:      (games)  => req('POST', '/api/games', {games}),
    getSettings:      ()       => req('GET',  '/api/settings'),
    updateSettings:   (d)      => req('POST', '/api/settings', d),
    getCustomers:     ()       => req('GET',  '/api/customers'),
    addCustomer:      (d)      => req('POST', '/api/customers', d),
    delCustomer:      (cid)    => req('DELETE','/api/customers/'+cid),
    stkPush:          (d)      => req('POST', '/api/stk', d),
    getStats:         ()       => req('GET',  '/api/stats'),
    estimateCharge:   (g,dur)  => req('POST', '/api/pricing/estimate',{game:g,duration:dur}),
    getIntegLog:      ()       => req('GET',  '/api/integrity/log'),
    verifyCheck:      (d)      => req('POST', '/api/integrity/verify', d),
    getIntegSchedule: (sid)    => req('GET',  '/api/integrity/schedule/'+sid),
  };
})();
