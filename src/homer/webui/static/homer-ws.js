/**
 * Homer Web UI: WebSocket-клиент.
 *
 * Подключается к /ws, обрабатывает события:
 *   - job.created
 *   - job.updated
 *   - job.removed
 *   - stats.updated
 * Обновляет DOM, перерисовывает таблицу.
 */
(function () {
  const RECONNECT_DELAY_MS = 2000;
  const PING_INTERVAL_MS = 25000;

  const state = {
    ws: null,
    pingTimer: null,
    jobs: new Map(),       // id -> job
    stats: {},
    filterStatus: null,
    filterQuery: '',
  };

  // ─────────── Утилиты ───────────

  function wsUrl() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const params = new URLSearchParams(location.search);
    // Basic Auth пробрасываем из ?user=&pass= (если настроено)
    // В реальном проекте — лучше через cookie/session
    return `${proto}//${location.host}/ws${location.search}`;
  }

  function escapeHtml(s) {
    return String(s)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;');
  }

  function statusColor(status) {
    return ({
      pending: 'warning',
      running: 'info',
      done: 'success',
      failed: 'danger',
      canceled: 'secondary',
      timeout: 'dark',
    })[status] || 'light';
  }

  function fmtDt(s) {
    if (!s) return '—';
    return s.replace('T', ' ').slice(0, 19);
  }

  // ─────────── Рендер ───────────

  function renderStats() {
    const el = document.getElementById('stats-container');
    if (!el) return;
    const html = Object.entries(state.stats)
      .map(([k, v]) => `
        <div class="card stat-card">
          <div class="card-body py-2 px-3">
            <div class="text-muted small">${escapeHtml(k)}</div>
            <div class="fs-4">${v}</div>
          </div>
        </div>
      `).join('');
    el.innerHTML = `<div class="d-flex flex-wrap gap-2">${html}</div>`;
  }

  function jobRow(j) {
    const actions = (() => {
      if (j.status === 'pending' || j.status === 'running') {
        return `<form method="post" action="/jobs/${j.id}/cancel" style="display:inline">
                  <button class="btn btn-sm btn-outline-danger">Отменить</button>
                </form>`;
      }
      if (['failed', 'timeout', 'canceled'].includes(j.status)) {
        return `<form method="post" action="/jobs/${j.id}/retry" style="display:inline">
                  <button class="btn btn-sm btn-outline-primary">Retry</button>
                </form>`;
      }
      return '';
    })();

    return `
      <tr data-job-id="${j.id}">
        <td><a href="/jobs/${j.id}">#${j.id}</a></td>
        <td>${escapeHtml(j.command)}</td>
        <td class="args" title='${escapeHtml(JSON.stringify(j.args))}'>${escapeHtml(JSON.stringify(j.args))}</td>
        <td>${j.priority}</td>
        <td><span class="badge bg-${statusColor(j.status)} badge-status">${j.status}</span></td>
        <td>${j.attempts}/${j.max_attempts}</td>
        <td>${fmtDt(j.created_at)}</td>
        <td>${fmtDt(j.started_at)}</td>
        <td>${fmtDt(j.finished_at)}</td>
        <td>${escapeHtml(j.triggered_by || '—')}</td>
        <td class="text-end">${actions}</td>
      </tr>
    `;
  }

  function passesFilter(j) {
    if (state.filterStatus && j.status !== state.filterStatus) return false;
    if (state.filterQuery) {
      const q = state.filterQuery.toLowerCase();
      const hay = (j.command + ' ' + JSON.stringify(j.args)).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  }

  function renderJobs() {
    const tbody = document.querySelector('#jobs-table tbody');
    if (!tbody) return;

    const rows = [...state.jobs.values()]
      .filter(passesFilter)
      .sort((a, b) => b.id - a.id)
      .map(jobRow)
      .join('');

    tbody.innerHTML = rows || `<tr><td colspan="11" class="text-center text-muted py-4">Задач нет</td></tr>`;
  }

  // ─────────── WS ───────────

  function connect() {
    const ws = new WebSocket(wsUrl());

    ws.onopen = () => {
      console.log('[homer-ws] connected');
      state.pingTimer = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send('ping');
      }, PING_INTERVAL_MS);
    };

    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); }
      catch { return; }

      switch (msg.type) {
        case 'job.created':
        case 'job.updated':
          state.jobs.set(msg.job.id, msg.job);
          renderJobs();
          break;
        case 'job.removed':
          state.jobs.delete(msg.job_id);
          renderJobs();
          break;
        case 'stats.updated':
          state.stats = msg.stats;
          renderStats();
          break;
        default:
          break;
      }
    };

    ws.onclose = () => {
      console.log('[homer-ws] disconnected, reconnect in', RECONNECT_DELAY_MS, 'ms');
      clearInterval(state.pingTimer);
      setTimeout(connect, RECONNECT_DELAY_MS);
    };

    ws.onerror = (e) => {
      console.warn('[homer-ws] error', e);
    };

    state.ws = ws;
  }

  // ─────────── Filters ───────────

  function initFilters() {
    const form = document.getElementById('jobs-filter');
    if (!form) return;
    const statusSel = form.querySelector('[name="status"]');
    const qInput = form.querySelector('[name="q"]');

    state.filterStatus = statusSel.value || null;
    state.filterQuery = qInput.value || '';

    form.addEventListener('input', () => {
      state.filterStatus = statusSel.value || null;
      state.filterQuery = qInput.value || '';
      renderJobs();
    });
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      renderJobs();
    });
  }

  // ─────────── Boot ───────────

  document.addEventListener('DOMContentLoaded', () => {
    initFilters();
    connect();
    // Первичная загрузка — через REST
    fetch('/api/jobs?limit=500')
      .then((r) => r.json())
      .then((jobs) => {
        state.jobs.clear();
        jobs.forEach((j) => state.jobs.set(j.id, j));
        renderJobs();
      })
      .catch((e) => console.warn('initial jobs load failed', e));

    fetch('/api/stats')
      .then((r) => r.json())
      .then((s) => { state.stats = s; renderStats(); })
      .catch(() => {});
  });
})();
