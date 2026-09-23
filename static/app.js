'use strict';
/*
 * Paper to Video — browser-side pipeline driver.
 *
 * The server does one bounded unit of work per request. This script sequences them:
 *   upload+OCR → plan → (render slide n → poll)* → (voice slide n)* → assemble → poll
 * Every step persists on the server, so a job can be resumed by id after a reload.
 */

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const POLL_RENDER_MS = 4000;
const POLL_ASSEMBLE_MS = 5000;

const state = {
  config: null,
  jobId: null,
  job: null,
  running: false,
  cancelRequested: false,
  passcode: '',
  file: null,
};

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------
async function api(path, opts = {}) {
  const headers = Object.assign({}, opts.headers || {});
  if (state.passcode) headers['X-Passcode'] = state.passcode;
  const res = await fetch(path, Object.assign({}, opts, { headers }));
  let body = null;
  try { body = await res.json(); } catch (_) { /* non-JSON */ }
  if (!res.ok) {
    const msg = (body && (body.detail || body.error)) || `${res.status} ${res.statusText}`;
    const err = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    err.status = res.status;
    throw err;
  }
  return body;
}

// ---------------------------------------------------------------------------
// Small UI helpers
// ---------------------------------------------------------------------------
const show = (el) => el && el.classList.remove('hidden');
const hide = (el) => el && el.classList.add('hidden');
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function toast(message, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), type === 'error' ? 8000 : 3000);
}

function setStatus(text, eta = '') {
  $('status-text').textContent = text;
  $('eta-text').textContent = eta;
}

function setStep(name, status, description) {
  const el = document.querySelector(`.workflow-step[data-step="${name}"]`);
  if (!el) return;
  el.classList.remove('active', 'completed', 'failed', 'pending');
  if (status) el.classList.add(status);
  el.querySelector('.step-status').textContent = { active: '…', completed: '✓', failed: '✗' }[status] || '';
  if (description) el.querySelector('.step-description').textContent = description;
}

function showError(message) {
  const box = $('error-box');
  box.textContent = message;
  show(box);
  toast(message, 'error');
}

function updateButtons() {
  const done = state.job && state.job.final && state.job.final.status === 'done';
  $('status-spinner').style.visibility = state.running ? 'visible' : 'hidden';
  state.running ? show($('cancel-btn')) : hide($('cancel-btn'));
  (!state.running && state.job && !done) ? show($('resume-run-btn')) : hide($('resume-run-btn'));
  (!state.running && state.job) ? show($('new-job-btn')) : hide($('new-job-btn'));
}

function slideKeys() {
  return Object.keys(state.job.slides || {}).sort((a, b) => Number(a) - Number(b));
}

function etaText() {
  if (!state.job || !state.job.slides) return '';
  const keys = slideKeys();
  const toRender = keys.filter((k) => !['done', 'failed'].includes(state.job.slides[k].status)).length;
  const toVoice = keys.filter((k) => state.job.slides[k].status !== 'failed' && (state.job.audio[k] || {}).status !== 'done').length;
  const secs = toRender * 75 + toVoice * 12 + (state.job.final.status === 'done' ? 0 : 90);
  return secs > 0 ? `about ${Math.max(1, Math.round(secs / 60))} min left` : '';
}

// ---------------------------------------------------------------------------
// Rendering the job document
// ---------------------------------------------------------------------------
function renderJob() {
  const job = state.job;
  if (!job) return;
  $('job-id-label').textContent = job.id;
  show($('pipeline-section'));
  hide($('upload-section'));

  setStep('ocr', job.has_markdown ? 'completed' : 'pending');
  setStep('plan', job.plan ? 'completed' : 'pending');
  updateStepCounts();
  renderPlan();
  renderVideos();
  renderFinal();
  updateButtons();
}

function updateStepCounts() {
  const job = state.job;
  const keys = slideKeys();
  if (!keys.length) return;
  const rendered = keys.filter((k) => job.slides[k].status === 'done').length;
  const failed = keys.filter((k) => job.slides[k].status === 'failed').length;
  const voiced = keys.filter((k) => (job.audio[k] || {}).status === 'done').length;
  const renderDone = rendered + failed === keys.length;
  setStep('render', renderDone ? (rendered ? 'completed' : 'failed') : (rendered ? 'active' : 'pending'),
    `${rendered}/${keys.length} rendered${failed ? `, ${failed} failed` : ''}`);
  setStep('voice', voiced === keys.length - failed && renderDone ? 'completed' : (voiced ? 'active' : 'pending'),
    `${voiced}/${keys.length} narrated`);
  const f = job.final.status;
  setStep('assemble', f === 'done' ? 'completed' : f === 'failed' ? 'failed' : ['submitted', 'rendering'].includes(f) ? 'active' : 'pending',
    f === 'done' ? 'Final video ready' : f === 'failed' ? (job.final.error || 'Assembly failed') : 'Shotstack stitches video and audio');
}

function renderPlan() {
  const plan = state.job.plan;
  if (!plan) return;
  show($('plan-section'));
  $('plan-title').textContent = plan.paper_title;
  $('plan-summary').textContent = plan.paper_summary;
  $('plan-slides-count').textContent = plan.slides.length;
  $('plan-slides').innerHTML = plan.slides.map((s) => `
    <div class="slide-card">
      <div class="slide-header">
        <span class="slide-num">${s.slide_number}</span>
        <h4>${esc(s.title)}</h4>
        <span class="type-badge">${esc(s.visual_type)}</span>
      </div>
      <div class="slide-body">
        <ul class="slide-points">${(s.key_points || []).map((p) => `<li>${esc(p)}</li>`).join('')}</ul>
        <p class="slide-script">${esc(s.voiceover_script)}</p>
      </div>
    </div>`).join('');
}

function renderVideos() {
  const keys = slideKeys();
  if (!keys.length) return;
  show($('videos-section'));
  $('video-grid').innerHTML = keys.map((k) => {
    const s = state.job.slides[k];
    const media = s.video_url
      ? `<video controls preload="metadata" ${s.thumbnail_url ? `poster="${esc(s.thumbnail_url)}"` : ''}><source src="${esc(s.video_url)}" type="video/mp4"></video>`
      : `<div class="video-placeholder">${s.status === 'failed' ? 'render failed' : s.status === 'pending' ? 'queued' : 'rendering…'}</div>`;
    const tier = s.tier_used ? `<span class="tier-badge">${esc(s.tier_used.replace('_', ' '))}</span>` : '';
    const err = s.status === 'failed' && s.error ? `<p class="hint">${esc(s.error.slice(0, 160))}</p>` : '';
    return `
      <div class="video-card">
        ${media}
        <h4>${s.slide_number}. ${esc(s.title)}</h4>
        <div class="video-meta"><span class="status-badge ${esc(s.status)}">${esc(s.status)}</span>${tier}</div>
        ${err}
      </div>`;
  }).join('');
}

function renderFinal() {
  const f = state.job.final;
  if (!f || f.status !== 'done' || !f.video_url) return;
  show($('final-section'));
  const player = $('final-player');
  if (player.src !== f.video_url) player.src = f.video_url;
  $('download-btn').href = f.video_url;
}

// ---------------------------------------------------------------------------
// Pipeline driver
// ---------------------------------------------------------------------------
function checkCancel() {
  if (state.cancelRequested) throw new Error('Paused. Click Resume to continue where you left off.');
}

async function runPipeline() {
  if (state.running) return;
  state.running = true;
  state.cancelRequested = false;
  hide($('error-box'));
  updateButtons();
  try {
    await stepPlan();
    await stepRender();
    await stepVoice();
    await stepAssemble();
    setStatus('Done. Your video is ready below.', '');
    toast('Video ready', 'success');
  } catch (e) {
    showError(e.message);
    setStatus('Stopped.', '');
  } finally {
    state.running = false;
    updateButtons();
    loadRecentJobs();
  }
}

async function stepPlan() {
  if (state.job.plan) { setStep('plan', 'completed'); return; }
  setStep('plan', 'active');
  setStatus('Claude is reading the paper and planning 11 slides…', 'usually 1 to 3 minutes');
  const r = await api(`/api/jobs/${state.jobId}/plan`, { method: 'POST' });
  state.job = r.job;
  renderJob();
}

async function stepRender() {
  const keys = slideKeys();
  const total = keys.length;
  for (const key of keys) {
    let s = state.job.slides[key];
    const n = s.slide_number;
    while (!['done', 'failed'].includes(s.status)) {
      checkCancel();
      if (s.status === 'pending' || s.status === 'retry') {
        setStatus(`Slide ${n}/${total}: Claude is writing the Manim scene (attempt ${s.tier} of 3)…`, etaText());
        const r = await api(`/api/jobs/${state.jobId}/slides/${n}/render`, { method: 'POST' });
        s = r.slide;
        state.job.slides[key] = s;
        if (r.fatal) throw new Error(s.error || 'A vendor rejected the request. Check the API keys and credits.');
      } else {
        setStatus(`Slide ${n}/${total}: Kodisc is rendering the animation…`, etaText());
        await sleep(POLL_RENDER_MS);
        checkCancel();
        const r = await api(`/api/jobs/${state.jobId}/slides/${n}`);
        s = r.slide;
        state.job.slides[key] = s;
        if (r.fatal) throw new Error(s.error || 'A vendor rejected the request. Check the API keys and credits.');
      }
      renderVideos();
      updateStepCounts();
    }
  }
  updateStepCounts();
  if (!keys.some((k) => state.job.slides[k].status === 'done')) {
    throw new Error('Every slide failed to render. See the slide cards for the errors.');
  }
}

async function stepVoice() {
  const keys = slideKeys();
  for (const key of keys) {
    const s = state.job.slides[key];
    const a = state.job.audio[key] || {};
    if (s.status !== 'done' || ['done', 'skipped'].includes(a.status)) continue;
    checkCancel();
    setStatus(`Slide ${s.slide_number}/${keys.length}: ElevenLabs is recording the narration…`, etaText());
    const r = await api(`/api/jobs/${state.jobId}/voice/${s.slide_number}`, { method: 'POST' });
    state.job.audio[key] = r.audio;
    updateStepCounts();
  }
}

async function stepAssemble() {
  let f = state.job.final;
  if (f.status === 'done') { updateStepCounts(); renderFinal(); return; }
  checkCancel();
  if (f.status === 'pending' || f.status === 'failed') {
    setStatus('Submitting the final edit to Shotstack…', etaText());
    const r = await api(`/api/jobs/${state.jobId}/assemble`, { method: 'POST' });
    f = r.final;
    state.job.final = f;
    state.job.step = r.step;
    updateStepCounts();
    if (f.status === 'failed') throw new Error(f.error || 'Shotstack rejected the edit');
  }
  while (['submitted', 'rendering'].includes(f.status)) {
    checkCancel();
    setStatus('Shotstack is stitching the slides and narration into one video…', 'usually 1 to 3 minutes');
    await sleep(POLL_ASSEMBLE_MS);
    const r = await api(`/api/jobs/${state.jobId}/assemble`);
    f = r.final;
    state.job.final = f;
    state.job.step = r.step;
    updateStepCounts();
  }
  if (f.status === 'failed') throw new Error(f.error || 'Final render failed');
  renderFinal();
}

// ---------------------------------------------------------------------------
// Entry points
// ---------------------------------------------------------------------------
async function startFromUpload() {
  if (!state.file) return;
  readPasscode();
  $('start-btn').disabled = true;
  hide($('error-box'));
  show($('pipeline-section'));
  hide($('upload-section'));
  setStep('ocr', 'active');
  setStatus('Uploading and extracting text with Mistral OCR…', 'usually under a minute');
  updateButtons();
  try {
    const fd = new FormData();
    fd.append('file', state.file);
    const r = await api('/api/jobs', { method: 'POST', body: fd });
    state.jobId = r.job.id;
    state.job = r.job;
    history.replaceState(null, '', `?job=${state.jobId}`);
    renderJob();
    await runPipeline();
  } catch (e) {
    if (e.status === 401) {
      showError('That passcode was not accepted.');
      resetToUpload();
      show($('passcode-row'));
      return;
    }
    showError(e.message);
    setStep('ocr', 'failed');
    state.job = null;
    updateButtons();
    show($('new-job-btn'));
  }
}

async function resumeJob(jobId) {
  jobId = (jobId || '').trim();
  if (!/^[a-f0-9]{8}$/.test(jobId)) { toast('Job ids are 8 hex characters', 'error'); return; }
  readPasscode();
  try {
    state.job = await api(`/api/jobs/${jobId}`);
  } catch (e) {
    showErrorInline(e.message);
    return;
  }
  state.jobId = jobId;
  history.replaceState(null, '', `?job=${jobId}`);
  renderJob();
  if (state.job.final.status === 'done') {
    setStatus('This job is complete.', '');
    return;
  }
  if (state.job.fatal) {
    showError(state.job.error || 'This job stopped on a vendor error. Fix the key or credits, then Resume.');
    setStatus('Stopped.', '');
    return;
  }
  await runPipeline();
}

function showErrorInline(msg) { toast(msg, 'error'); }

function resetToUpload() {
  state.jobId = null;
  state.job = null;
  state.file = null;
  state.running = false;
  state.cancelRequested = false;
  history.replaceState(null, '', location.pathname);
  ['pipeline-section', 'plan-section', 'videos-section', 'final-section', 'error-box', 'file-info'].forEach((id) => hide($(id)));
  ['ocr', 'plan', 'render', 'voice', 'assemble'].forEach((s) => setStep(s, null));
  $('file-input').value = '';
  $('start-btn').disabled = true;
  show($('upload-section'));
  loadRecentJobs();
}

function readPasscode() {
  state.passcode = $('passcode-input').value.trim();
  try { sessionStorage.setItem('p2v_passcode', state.passcode); } catch (_) { /* private mode */ }
}

// ---------------------------------------------------------------------------
// Upload widget
// ---------------------------------------------------------------------------
function handleFile(file) {
  if (!file) return;
  if (!/\.pdf$/i.test(file.name)) { toast('Please choose a PDF', 'error'); return; }
  const max = (state.config && state.config.max_upload_mb) || 25;
  if (file.size > max * 1024 * 1024) { toast(`PDF is larger than ${max} MB`, 'error'); return; }
  state.file = file;
  $('file-name').textContent = `${file.name} (${(file.size / 1024 / 1024).toFixed(1)} MB)`;
  show($('file-info'));
  $('start-btn').disabled = false;
}

function wireUpload() {
  const zone = $('drop-zone');
  const input = $('file-input');
  zone.addEventListener('click', (e) => { if (e.target.tagName !== 'LABEL') input.click(); });
  input.addEventListener('change', () => handleFile(input.files[0]));
  ['dragenter', 'dragover'].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add('dragover'); }));
  ['dragleave', 'drop'].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.remove('dragover'); }));
  zone.addEventListener('drop', (e) => handleFile(e.dataTransfer.files[0]));
  $('remove-file').addEventListener('click', () => { state.file = null; input.value = ''; hide($('file-info')); $('start-btn').disabled = true; });
  $('start-btn').addEventListener('click', startFromUpload);
  $('resume-btn').addEventListener('click', () => resumeJob($('resume-input').value));
  $('resume-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') resumeJob($('resume-input').value); });
  $('cancel-btn').addEventListener('click', () => { state.cancelRequested = true; setStatus('Pausing after the current step…', ''); });
  $('resume-run-btn').addEventListener('click', () => runPipeline());
  $('new-job-btn').addEventListener('click', resetToUpload);
  $('new-job-btn-2').addEventListener('click', resetToUpload);
}

// ---------------------------------------------------------------------------
// Gallery + recent jobs
// ---------------------------------------------------------------------------
function renderGallery(samples) {
  if (!samples || !samples.length) return;
  $('gallery').innerHTML = samples.map((s) => `
    <div class="video-card">
      <video controls preload="metadata" ${s.poster ? `poster="${esc(s.poster)}"` : ''}><source src="${esc(s.url)}" type="video/mp4"></video>
      <h4>${esc(s.title || 'Sample')}</h4>
    </div>`).join('');
  show($('gallery-section'));
}

async function loadRecentJobs() {
  try {
    const r = await api('/api/jobs');
    const jobs = (r.jobs || []).slice(0, 8);
    $('recent-jobs').innerHTML = jobs.length ? jobs.map((j) => `
      <div class="job-card" data-id="${esc(j.id)}">
        <span class="job-card-id">${esc(j.id)}</span>
        <div class="job-card-info">
          <div class="job-card-name">${esc(j.paper_title || j.filename)}</div>
          <div class="job-card-status">
            <span class="job-card-badge ${j.final_status === 'done' ? 'complete' : 'partial'}">${esc(j.final_status === 'done' ? 'complete' : j.step)}</span>
            <span>${j.slides_rendered}/${j.slides_total} slides</span>
          </div>
        </div>
        <span class="job-card-arrow">→</span>
      </div>`).join('') : '<p class="hint">No jobs yet.</p>';
    $('recent-jobs').querySelectorAll('.job-card').forEach((el) => el.addEventListener('click', () => resumeJob(el.dataset.id)));
  } catch (_) { /* listing is optional */ }
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
async function init() {
  wireUpload();
  try { state.passcode = sessionStorage.getItem('p2v_passcode') || ''; } catch (_) { /* ignore */ }
  $('passcode-input').value = state.passcode;
  try {
    state.config = await api('/api/config');
    if (state.config.passcode_required) show($('passcode-row'));
    renderGallery(state.config.samples);
    const missing = Object.entries(state.config.services || {}).filter(([k, v]) => v === false).map(([k]) => k);
    if (missing.length) toast(`Not configured yet: ${missing.join(', ')}`, 'error');
  } catch (e) {
    toast(`Cannot reach the API: ${e.message}`, 'error');
  }
  loadRecentJobs();
  const jobId = new URLSearchParams(location.search).get('job');
  if (jobId) resumeJob(jobId);
}

document.addEventListener('DOMContentLoaded', init);
