/* Scopewatch — the operating field instrument, driven by the real service.
 *
 * No framework, no build step. The HTTP surface comes from servicekit's shared
 * api.js; everything below turns one RunRecord into the screens in
 * docs/mockups/operating-field.html.
 */
import { api, ApiError } from '/shell/js/api.js';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const state = {
  jobId: null, record: null, agent: null, sample: null, evaluation: null,
  videoUrl: null, events: [], evidence: [], geom: null, closeStream: null, polling: null,
  cursorMs: 0, decodable: true,
};

const PHASE_NAMES = {
  preparation: 'Preparation', exposure: 'Exposure', dissection: 'Dissection',
  critical_approach: 'Critical approach', division: 'Division', extraction: 'Extraction',
};
// Each refusal code in the words a person uses, and the thing that would fix it.
const REFUSALS = {
  OUT_OF_FOCUS: ['no usable edge energy in the frame', 'Refocus the scope and record again.'],
  LENS_FOGGED: ['haze or smoke across the lens', 'Clean the lens, or submit a clip where the cavity is clear.'],
  OCCLUDED: ['too much of the field covered', 'Pull back until the field, not the instrument, fills the frame.'],
  EXPOSURE_CLIPPED: ['the frame is clipped', 'Lower the light source; the sensor is saturating.'],
  NO_SCALE_REFERENCE: ['no instrument shaft in view, so no scale',
    'Bring an instrument shaft into view for a few seconds, or set millimetres per pixel directly.'],
  SCALE_INCONSISTENT: ['the shaft scale wandered too much across the case',
    'The blood-covered share still stands. A volume needs a scale that holds steady; set millimetres per pixel directly if you know it.'],
  OUT_OF_DOMAIN: ['not a laparoscopic view of the abdomen',
    'Scopewatch reads laparoscopic video from inside the abdomen. Open surgery, drapes and gloved hands are refused.'],
  NO_USABLE_FRAMES: ['no frame in the clip was good enough to measure',
    'Submit a clip with the scope inside the cavity and the light on.'],
  DECODE_FAILED: ['the file could not be decoded as video', 'Submit an MP4, AVI or MOV the decoder can open.'],
};
const refusalWord = (code) => REFUSALS[code]?.[0] || 'refused by a quality gate';
const refusalNext = (code) => REFUSALS[code]?.[1] || 'Submit a clip where the cavity is lit, in focus and not obscured.';

/* ────────────────────────── formatting ────────────────────────── */
const pad = (n) => String(n).padStart(2, '0');

function clock(ms) {
  if (ms == null || !isFinite(ms)) return 'not known';
  const t = Math.max(0, Math.round(ms / 1000));
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
  return h ? `${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}
function num(v, d = 2) {
  if (v == null || !isFinite(v)) return 'not measured';
  return Number(v).toFixed(d);
}
function ms(v) { return v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`; }
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function sentence(s) {
  const t = String(s ?? '').replace(/_/g, ' ');
  return t.charAt(0).toUpperCase() + t.slice(1);
}
function localTime(epochSeconds) {
  if (!epochSeconds) return '';
  return new Date(epochSeconds * 1000).toLocaleTimeString([], { hour12: false });
}

/* ────────────────────────── boot ────────────────────────── */
async function boot() {
  try {
    const [cfg, ver] = await Promise.all([api.config(), api.version()]);
    $('#st-opencv').textContent = `${ver.opencv_version || cfg.opencv_version || 'unknown'}`;
    document.title = `${cfg.product?.title || 'Scopewatch'} — operating field instrument`;
  } catch (err) { showError(err); }

  try {
    const res = await fetch('/api/sample');
    state.sample = await res.json();
    if (!res.ok) throw new Error(state.sample?.error?.message || 'no sample');
    const mb = (state.sample.bytes / 1048576).toFixed(1);
    $('#sample-line').textContent =
      `${state.sample.filename}, ${mb} MB. A synthetic case whose bleed onset, fog window and scale are known by construction. Real clips read differently; the evaluation says how.`;
  } catch {
    $('#sample-line').textContent = 'No sample clip is bundled in this image. Choose a clip of your own.';
    $('#run-sample').disabled = true;
  }

  try {
    const res = await fetch('/api/evaluation');
    if (res.ok) state.evaluation = await res.json();
  } catch { /* the page works without it */ }

  const cost = $('#railfoot').dataset.cost || '';
  const [inst, rate] = cost.split('—').map((s) => s.trim());
  if (inst) $('#st-inst').textContent = inst;
  if (rate) $('#st-cost').textContent = rate;

  $('#run-sample').addEventListener('click', runSample);
  $('#file-input').addEventListener('change', (e) => {
    const file = e.target.files?.[0];
    if (file) runFile(file);
  });

  $('#cp-actor').addEventListener('input', syncCheckpointButtons);
  $('#cp-reason').addEventListener('change', syncCheckpointButtons);
  $('#cp-confirm').addEventListener('click', () => decide('confirm'));
  $('#cp-dismiss').addEventListener('click', () => decide('dismiss'));

  const video = $('#video');
  video.addEventListener('timeupdate', () => { state.cursorMs = video.currentTime * 1000; onPlayhead(); });
  video.addEventListener('seeked', () => { state.cursorMs = video.currentTime * 1000; onPlayhead(); });
  // A <video> with nothing painted reads as a broken panel, so park the playhead
  // on the frame the case is actually about as soon as there is one to park on.
  video.addEventListener('loadeddata', () => {
    checkCodec();
    if (video.currentTime > 0.05) return;
    const onset = state.record?.metrics?.onset;
    seek(onset?.detected ? onset.timestamp_ms : 100);
  });
  video.addEventListener('error', () => setDecodable(false));
  video.addEventListener('canplay', checkCodec);

  let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { drawTrace(); onPlayhead(); }, 140);
  });

  watchSections();
  renderEmpty();
}

/* ────────────────────────── running a job ────────────────────────── */
async function runSample() {
  try {
    const res = await fetch(state.sample?.url || '/api/sample/download');
    if (!res.ok) throw new Error(`the sample clip could not be fetched (${res.status})`);
    const blob = await res.blob();
    const name = state.sample?.filename || 'sample-case.mp4';
    await runFile(new File([blob], name, { type: blob.type || 'video/mp4' }));
  } catch (err) { showError(err); busy(false); }
}

async function runFile(file) {
  busy(true);
  hideError();
  if (state.closeStream) { state.closeStream(); state.closeStream = null; }
  clearInterval(state.polling);

  if (state.videoUrl) URL.revokeObjectURL(state.videoUrl);
  state.videoUrl = URL.createObjectURL(file);
  state.cursorMs = 0;
  state.decodable = true;
  const video = $('#video');
  video.hidden = false;
  video.src = state.videoUrl;
  $('#field-img').hidden = true;
  $('#vid-nocodec').hidden = true;
  $('#vid-empty').hidden = true;
  setTimeout(checkCodec, 1500);
  $('#tb-file').textContent = file.name;
  $('#tb-dot').className = 'dot warn';

  $('#prog').hidden = false;
  $('#prog-notes').innerHTML = '';
  progress(0, 'Uploading the clip.');

  try {
    const { job_id: jobId } = await api.submit(file, {});
    state.jobId = jobId;
    state.closeStream = api.events(jobId, {
      progress: (d) => progress(d.percent ?? 0, d.message || ''),
      note: (d) => addNote(d.message || ''),
      status: (d) => { if (d.status === 'failed' && d.error) showError(new ApiError(d.error, 500)); },
      end: () => finish(jobId),
      error: () => { /* the poller below is the safety net */ },
    });
    state.polling = setInterval(async () => {
      try {
        const job = await api.job(jobId);
        if (job.status === 'done' || job.status === 'failed') finish(jobId);
      } catch { /* keep polling */ }
    }, 2500);
  } catch (err) { showError(err); busy(false); $('#prog').hidden = true; }
}

async function finish(jobId) {
  clearInterval(state.polling);
  if (state.closeStream) { state.closeStream(); state.closeStream = null; }
  try {
    const job = await api.job(jobId);
    if (job.status === 'failed') {
      showError(new ApiError(job.error || { message: 'the analysis failed' }, 500));
      $('#prog').hidden = true; busy(false); return;
    }
    state.record = job.result;
    try {
      const res = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/checkpoints`);
      state.agent = res.ok ? await res.json() : state.record?.metrics?.agent || null;
    } catch { state.agent = state.record?.metrics?.agent || null; }
    progress(100, 'Done.');
    setTimeout(() => { $('#prog').hidden = true; }, 700);
    renderAll();
  } catch (err) { showError(err); }
  busy(false);
}

function busy(on) {
  const b = $('#run-sample');
  b.disabled = on;
  b.lastChild.textContent = on ? ' Analysing the case…' : ' Run the bundled sample';
}
function progress(pct, message) {
  $('#prog-fill').style.width = `${Math.max(0, Math.min(100, pct))}%`;
  $('#prog-pct').textContent = `${Math.round(pct)}%`;
  if (message) $('#prog-msg').textContent = sentence(message);
}
function addNote(message) {
  if (!message) return;
  const li = document.createElement('li');
  li.textContent = sentence(message);
  $('#prog-notes').prepend(li);
}
function showError(err) {
  const box = $('#errbox');
  const code = err instanceof ApiError ? err.code : (err?.name || 'ERROR');
  box.innerHTML = `<b>${esc(code)}</b>${esc(err?.message || 'something went wrong')}`;
  const offered = err?.details?.reasons_offered;
  if (Array.isArray(offered) && offered.length) {
    box.innerHTML += `<p style="margin-top:6px;color:var(--fg-muted)">Reasons the server will accept: ${esc(offered.join('; '))}.</p>`;
  }
  box.hidden = false;
}
function hideError() { $('#errbox').hidden = true; }

/* ────────────────────────── rendering ────────────────────────── */
function renderEmpty() {
  $('#kpis').innerHTML = ['Blood-covered field, peak', 'Blood on the field, volume', 'Bleeding onset',
    'Frames measurable', 'Safety checkpoint']
    .map((k) => `<div class="kpi"><div class="k">${esc(k)}</div><div class="v faint">not measured</div>
      <div class="n">no case has been analysed yet</div></div>`).join('');
  $('#cr-body').innerHTML = `<p style="padding:11px 13px;color:var(--fg-faint)">No checkpoint has been raised. The automatic checkpoint is experimental and off by default: on real video its cue, instrument width, cannot tell a clip applier from a grasper nearer the lens.</p>`;
  $('#ev-body').innerHTML = `<tr><td colspan="3" class="faint">The log fills with the agent's own transitions once a case has run.</td></tr>`;
  $('#in-body').innerHTML = `<div class="cell"><h3>Cost of a run</h3>
    <div class="kv"><span>Instance</span><span>${esc($('#st-inst').textContent)}</span></div>
    <div class="kv"><span>Rate</span><span>${esc($('#st-cost').textContent)}</span></div></div>`;
  drawTrace();
}

function renderAll() {
  const rec = state.record;
  if (!rec) return;
  const cannot = isUnmeasurable(rec);

  renderTopbar(rec, cannot);
  renderHead(rec, cannot);
  renderCannot(rec, cannot);
  state.events = buildEvents(rec);
  state.evidence = pickEvidence(rec);
  renderKpis(rec);
  renderCheckpoint();
  renderEvents();
  renderEvidence();
  renderInstruments(rec);
  renderRail(rec);
  renderPhases(rec);
  drawTrace();
  checkCodec();
  if (state.cursorMs < 50) {
    const onset = rec.metrics?.onset;
    seek(onset?.detected ? onset.timestamp_ms : 100);
  }
  onPlayhead();
  $('#foot-run').textContent = `Run ${rec.run_id} · OpenCV ${rec.env?.opencv_version || '—'} · analysed in ${ms(rec.timings?.total_ms || 0)}`;
}

function isUnmeasurable(rec) {
  const q = rec.metrics?.quality;
  return Boolean(rec.refused) || (q && q.frames > 0 && q.usable_fraction < 0.5);
}

function renderTopbar(rec, cannot) {
  const v = rec.metrics?.video || {};
  $('#tb-file').textContent = rec.input?.filename || 'case';
  $('#tb-duration').textContent = clock(v.duration_ms);
  $('#tb-video').textContent = v.width
    ? `${v.width}×${v.height}, ${num(v.fps, 0)} fps, ${v.frame_count || 0} frames`
    : 'resolution not read';
  const open = state.agent?.open_checkpoint;
  $('#tb-dot').className = `dot ${cannot ? 'warn' : open ? 'hot' : ''}`.trim();
  const chip = $('#tb-state');
  if (cannot) { chip.className = 'chip warn'; chip.textContent = '▲ Measurement suspended'; }
  else if (open) { chip.className = 'chip hot'; chip.textContent = '▲ Step held'; }
  else { chip.className = 'chip ok'; chip.textContent = '✓ Case measured'; }
}

function renderHead(rec, cannot) {
  const open = state.agent?.open_checkpoint;
  if (cannot) {
    $('#page-title').textContent = 'The field cannot be measured';
    $('#page-lede').textContent =
      'The clip was read and the gates were applied. Too little of it is measurable to publish a number, so nothing is guessed.';
  } else if (open) {
    $('#page-title').textContent = 'Checkpoint — the safety view has not been recorded';
    $('#page-lede').textContent =
      'The phase reached the approach to the irreversible step with no recorded safety view. Nothing is blocked; the instrument records who decided what, and why.';
  } else {
    $('#page-title').textContent = 'Live field';
    $('#page-lede').textContent =
      'The share of the visible field covered in blood, measured frame by frame, and how fast it changes. A volume appears only when the instrument scale holds steady, and no volume has been validated on real footage.';
  }
  if (rec.warnings?.length) {
    $('#page-lede').textContent += ` ${rec.warnings[0]}`;
  }
}

function renderCannot(rec, cannot) {
  const box = $('#cannot');
  box.hidden = !cannot;
  if (!cannot) return;
  const q = rec.metrics?.quality || {};
  const refusal = rec.refusals?.[0];
  const code = refusal?.code || 'NO_USABLE_FRAMES';
  $('#cannot-why').textContent = refusal
    ? `${refusal.message} Of ${q.frames || 0} frames read, ${q.usable || 0} passed the gates — ${num((q.usable_fraction || 0) * 100, 1)} per cent.`
    : `Of ${q.frames || 0} frames read, only ${q.usable || 0} passed the gates — ${num((q.usable_fraction || 0) * 100, 1)} per cent. Below half, a number would be a guess dressed as a measurement.`;
  $('#cannot-next').textContent = `Next action: ${refusal?.details?.hint || refusalNext(code)}`;
  const counts = q.rejected_by || {};
  const rows = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  $('#cannot-codes').innerHTML = rows.length
    ? `<table><thead><tr><th style="width:200px">Refusal</th><th>Why the frame was refused</th><th class="num" style="width:110px">Frames</th></tr></thead><tbody>${
      rows.map(([c, n]) => `<tr><td><span class="chip warn">${esc(c)}</span></td>
        <td class="dim">${esc(refusalWord(c))}</td>
        <td class="num">${n}</td></tr>`).join('')}</tbody></table>`
    : '<p class="faint">No frame carried a refusal code.</p>';
}

function realSegmentationLine() {
  const seg = state.evaluation?.real?.segmentation?.after?.test;
  if (!seg || seg.precision == null) return '';
  return ` On hand-labelled frames from held-out real clips: precision ${num(seg.precision * 100, 0)}%, recall ${num(seg.recall * 100, 0)}%.`;
}

function renderKpis(rec) {
  const rows = rec.results || [];
  $('#kpis').innerHTML = rows.map((r) => {
    let value, unit = r.unit ? `<u>${esc(r.unit)}</u>` : '', cls = '', note = r.note || '';
    if (r.label === 'Safety checkpoint') {
      if (r.value === 'off') {
        return `<div class="kpi"><div class="k">${esc(r.label)}</div>
          <div class="v faint">Off</div><div class="n">${esc(note)}</div></div>`;
      }
      const st = state.agent?.state || r.value;
      value = sentence(st); unit = '';
      cls = st === 'held' ? 'hot' : (st === 'confirmed' ? 'good' : '');
      const cp = openCheckpoint();
      note = cp ? `held at ${clock(cp.at_ms)}, frame ${cp.frame_index}, waiting on a person. Experimental.`
        : (state.agent?.checkpoints?.length ? decidedLine(state.agent.checkpoints.slice(-1)[0]) : note);
    } else if (r.status === 'CANNOT_MEASURE') {
      return `<div class="kpi"><div class="k">${esc(r.label)}</div>
        <div class="v faint warnfg">Cannot measure</div><div class="n">${esc(note.replace(/^CANNOT_MEASURE: /, ''))}</div></div>`;
    } else if (!r.measured || r.value == null) {
      return `<div class="kpi"><div class="k">${esc(r.label)}</div>
        <div class="v faint">not measured</div><div class="n">${esc(note)}</div></div>`;
    } else if (r.label === 'Bleeding onset') {
      value = clock(r.value * 1000);
      unit = r.plus_minus ? `<u>± ${num(r.plus_minus, 1)} s</u>` : '';
      cls = 'hot';
    } else if (typeof r.value === 'string') {
      value = sentence(r.value); unit = '';
    } else {
      value = num(r.value, r.unit === '%' ? 1 : (r.value < 10 ? 2 : 1));
      if (r.low != null && r.high != null) note = `${num(r.low, 2)} to ${num(r.high, 2)} ${r.unit}. ${note}`;
      if (r.label === 'Frames measurable') cls = r.value >= 50 ? 'good' : '';
      if (r.label.startsWith('Blood-covered')) note = `Share of the visible field segmented as blood.${realSegmentationLine()}`;
    }
    return `<div class="kpi ${cls}"><div class="k">${esc(r.label)}</div>
      <div class="v">${esc(value)}${unit}</div><div class="n">${esc(note)}</div></div>`;
  }).join('');
}

function openCheckpoint() {
  const id = state.agent?.open_checkpoint;
  if (!id) return null;
  return (state.agent.checkpoints || []).find((c) => c.checkpoint_id === id) || null;
}
function decidedLine(cp) {
  if (!cp || !cp.decided_by) return 'no checkpoint has been answered';
  const word = cp.state === 'confirmed' ? 'confirmed' : 'dismissed with a reason';
  return `${word} by ${cp.decided_by} at ${localTime(cp.decided_at)}`;
}

/* ────────────────────── checkpoint card ────────────────────── */
function renderCheckpoint() {
  const card = $('#checkpoint-card'), resolved = $('#checkpoint-resolved');
  const cps = state.agent?.checkpoints || [];
  const open = openCheckpoint();
  const last = cps.length ? cps[cps.length - 1] : null;

  card.hidden = !open;
  resolved.hidden = !(last && !open);

  if (open) {
    $('#cp-hold').innerHTML =
      `<svg width="18" height="18" viewBox="0 0 18 18" fill="none" aria-hidden="true"><path d="M9 1.6l7.4 13H1.6z" stroke="#0B1210" stroke-width="1.8" stroke-linejoin="round"/><path d="M9 6.6v3.4" stroke="#0B1210" stroke-width="1.9" stroke-linecap="round"/><circle cx="9" cy="12.2" r="1" fill="#0B1210"/></svg>
       Held at ${esc(clock(open.at_ms))} — frame ${open.frame_index} pinned as evidence
       <span style="margin-left:auto">Phase ${esc(PHASE_NAMES[open.phase] || open.phase)}</span>`;
    $('#cp-question').textContent = open.question;
    $('#cp-context').textContent = state.agent?.autonomy || '';
    const sel = $('#cp-reason');
    if (sel.options.length <= 1) {
      (open.reasons_offered || []).forEach((r) => {
        const o = document.createElement('option');
        o.value = r; o.textContent = r; sel.appendChild(o);
      });
    }
    $('#cp-live').textContent = `A safety checkpoint is held at ${clock(open.at_ms)} and is waiting on a named person.`;
    syncCheckpointButtons();
  }
  if (last && !open) {
    const confirmed = last.state === 'confirmed';
    $('#cpr-chip').className = `chip ${confirmed ? 'ok' : ''}`;
    $('#cpr-chip').textContent = confirmed ? '✓ Confirmed' : '● Reason recorded';
    $('#cpr-line').textContent = confirmed
      ? `${last.decided_by} confirmed the critical view of safety was established.`
      : `${last.decided_by} proceeded without confirming, and gave a reason.`;
    $('#cpr-reason').textContent = [last.reason, last.note].filter(Boolean).join(' — ') ||
      'No further note was recorded.';
    $('#cpr-meta').textContent =
      `Raised at ${clock(last.at_ms)} on frame ${last.frame_index}. Answered at ${localTime(last.decided_at)} local time. The decision is in the same transition log as the perception that raised it.`;
    $('#cp-live').textContent = `Checkpoint ${last.state} by ${last.decided_by}.`;
  }

  const sub = $('#cr-sub');
  sub.textContent = cps.length ? `${cps.length} raised · agent ${state.agent?.state || 'observing'}` : 'none raised';
  $('#cr-body').innerHTML = cps.length
    ? `<table><thead><tr><th style="width:86px">Time</th><th>Decision</th><th style="width:110px">By</th></tr></thead><tbody>${
      cps.map((c) => {
        const chip = c.state === 'held' ? '<span class="chip hot">Awaiting</span>'
          : c.state === 'confirmed' ? '<span class="chip ok">Confirmed</span>'
            : '<span class="chip">Reason given</span>';
        const why = c.state === 'dismissed' && c.reason ? esc(c.reason) : 'Safety view before the irreversible step';
        return `<tr class="seek" data-ms="${c.at_ms}"><td class="mono dim">${esc(clock(c.at_ms))}</td>
          <td>${chip} ${why}</td><td class="dim">${esc(c.decided_by || 'nobody yet')}</td></tr>`;
      }).join('')}</tbody></table>`
    : `<p style="padding:11px 13px;color:var(--fg-faint)">${state.record?.metrics?.checkpoint?.automatic
      ? 'No checkpoint was raised in this case. The phase never reached the irreversible step without a recorded safety view.'
      : 'The automatic checkpoint is off for this run. It is experimental: on real video its image cue, instrument width, cannot tell a clip applier from a grasper nearer the lens.'}</p>`;
  wireSeek($('#cr-body'));
}

function syncCheckpointButtons() {
  const actor = $('#cp-actor').value.trim();
  const reason = $('#cp-reason').value;
  $('#cp-confirm').disabled = !actor;
  $('#cp-dismiss').disabled = !(actor && reason);
}

async function decide(kind) {
  const cp = openCheckpoint();
  if (!cp || !state.jobId) return;
  const body = {
    actor: $('#cp-actor').value.trim(),
    note: $('#cp-note').value.trim(),
  };
  if (kind === 'dismiss') body.reason = $('#cp-reason').value;
  $('#cp-confirm').disabled = $('#cp-dismiss').disabled = true;
  hideError();
  try {
    const url = `/api/jobs/${encodeURIComponent(state.jobId)}/checkpoints/${encodeURIComponent(cp.checkpoint_id)}/${kind}`;
    const res = await fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const payload = await res.json().catch(() => null);
    if (!res.ok) throw new ApiError(payload?.error || { message: res.statusText }, res.status);
    state.agent = payload.agent;
    state.events = buildEvents(state.record);
    renderCheckpoint();
    renderKpis(state.record);
    renderEvents();
    renderRail(state.record);
    $('#checkpoint-resolved').scrollIntoView({ block: 'nearest' });
  } catch (err) {
    showError(err);
    syncCheckpointButtons();
  }
}

/* ────────────────────────── the event log ────────────────────────── */
const ACTION_TEXT = {
  rescan_window: (d) => `Re-read ${clock(d.start_ms)} to ${clock(d.end_ms)} at full frame rate`,
  record_onset: () => 'Onset recorded from the coarse pass',
  request_clean_lens: (d) => `Clean lens requested — ${d.consecutive_fogged_frames} fogged frames suppressed onset detection`,
  hold_checkpoint: () => 'Checkpoint held for a named person',
  resume: () => 'Resumed observing; the phase left the critical approach',
};
const ACTION_VALUE = {
  rescan_window: (d, a) => a.result?.frames_read != null ? `${a.result.frames_read} frames` : `stride ${d.stride}`,
  record_onset: (d) => d.field_fraction != null ? `${num(d.field_fraction * 100, 1)}% of field` : 'recorded',
  request_clean_lens: () => 'suppressed',
  hold_checkpoint: () => 'held',
  resume: () => 'observing',
};

function buildEvents(rec) {
  const out = [];
  const agent = state.agent || rec.metrics?.agent || {};
  const onset = rec.metrics?.onset;

  if (onset?.detected) {
    out.push({
      ms: onset.timestamp_ms, cls: 'hotfg',
      text: `Bleeding onset — rate crossed ${num(onset.threshold_per_min, 1)} ${onset.unit || ''}`,
      value: `${num(onset.rate_per_min, 1)} ${onset.unit || ''}`,
    });
  }
  (agent.actions || []).forEach((a) => {
    const text = (ACTION_TEXT[a.kind] || (() => sentence(a.kind)))(a.detail || {}, a);
    const value = (ACTION_VALUE[a.kind] || (() => (a.performed ? 'performed' : 'planned')))(a.detail || {}, a);
    out.push({ ms: a.at_ms, text, value, cls: a.performed ? '' : 'dim', uri: a.evidence_uri });
  });
  (agent.transitions || []).forEach((t) => {
    const human = t.actor && t.actor !== 'system';
    out.push({
      ms: t.at_ms,
      text: `${sentence(t.from)} to ${sentence(t.to)} — ${t.trigger}${t.reason ? `: ${t.reason}` : ''}`,
      value: human ? t.actor : 'system',
      cls: t.to === 'held' ? 'hotfg' : (t.to === 'confirmed' ? 'okfg' : 'dim'),
      uri: t.evidence_uri,
    });
  });

  // Runs where the gates refused to measure. The suspension is itself a measurement.
  const s = rec.metrics?.series;
  if (s?.measurable?.length) {
    const codesAt = (a, b) => {
      const set = new Set();
      (rec.evidence || []).forEach((e) => {
        const code = e.metrics?.refusal;
        if (code && e.timestamp_ms >= a - 1 && e.timestamp_ms <= b + 1) set.add(code);
      });
      return Array.from(set);
    };
    let i = 0;
    while (i < s.measurable.length) {
      if (s.measurable[i]) { i += 1; continue; }
      let j = i;
      while (j + 1 < s.measurable.length && !s.measurable[j + 1]) j += 1;
      const a = s.times_ms[i], b = s.times_ms[j];
      const codes = codesAt(a, b);
      out.push({
        ms: a, cls: 'warnfg',
        text: `Measurement suspended for ${((b - a) / 1000 + 0.1).toFixed(1)} s — ${codes.length ? codes.map(refusalWord).join(', ') : 'the frame failed a quality gate'}`,
        value: `${j - i + 1} frames`,
      });
      i = j + 1;
    }
  }
  return out.sort((x, y) => y.ms - x.ms);
}

function renderEvents() {
  const rows = state.events;
  $('#ev-sub').textContent = `${rows.length} event${rows.length === 1 ? '' : 's'}`;
  $('#ev-body').innerHTML = rows.length
    ? rows.map((e) => `<tr class="seek" data-ms="${e.ms}" tabindex="0">
        <td class="mono dim">${esc(clock(e.ms))}</td>
        <td>${esc(e.text)}</td>
        <td class="num ${e.cls === 'dim' ? 'dim' : esc(e.cls)}">${esc(e.value)}</td></tr>`).join('')
    : '<tr><td colspan="3" class="faint">Nothing happened that was worth a line in the log.</td></tr>';
  wireSeek($('#ev-body'));
}

function wireSeek(root) {
  $$('.seek', root).forEach((tr) => {
    tr.tabIndex = 0;
    tr.addEventListener('click', () => seek(Number(tr.dataset.ms)));
    tr.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); seek(Number(tr.dataset.ms)); }
    });
  });
}

function seek(msValue) {
  if (!isFinite(msValue)) return;
  const video = $('#video');
  state.cursorMs = Math.max(0, msValue);
  if (video.src && state.decodable) {
    try { video.currentTime = state.cursorMs / 1000; } catch { /* not seekable yet */ }
    video.pause();
  }
  onPlayhead();
}

/* Not every laparoscopic clip is in a codec a browser can decode — the bundled
 * sample is MPEG-4 Part 2, which Chromium will not touch. Rather than leave a
 * black rectangle where the field should be, the panel falls back to the frames
 * the measurement was actually made on and says so. */
function checkCodec() {
  const video = $('#video');
  if (!video.src) return;
  const broken = Boolean(video.error) || (video.readyState >= 2 && video.videoWidth === 0);
  setDecodable(!broken);
}

function setDecodable(ok) {
  if (state.decodable === ok) return;
  state.decodable = ok;
  const video = $('#video');
  video.hidden = !ok;
  $('#field-img').hidden = ok;
  const note = $('#vid-nocodec');
  note.hidden = ok;
  $('#live-field').classList.toggle('fallback', !ok);
  if (!ok) {
    note.innerHTML = '<b>This browser cannot decode the clip.</b> Showing the overlay frames the measurement was made on. Click an event, a phase or an evidence frame to move through the case.';
    $('#vid-empty').hidden = true;
  }
  onPlayhead();
}

/* ────────────────────────── evidence ────────────────────────── */
function pickEvidence(rec) {
  const all = rec.evidence || [];
  if (all.length <= 10) return all;
  // Every measured frame earns its place. Refused frames earn two each at most:
  // ten pictures of the same complaint is a wall, not evidence.
  const picked = [];
  const perCode = new Map();
  all.forEach((e) => {
    const code = e.metrics?.refusal;
    if (!code) { picked.push(e); return; }
    const n = perCode.get(code) || 0;
    if (n < 3) { perCode.set(code, n + 1); picked.push(e); }
  });
  // A clip that refused everything still deserves a strip worth looking at.
  const seen = new Set(picked.map((e) => e.uri));
  const step = Math.max(1, Math.floor(all.length / 6));
  for (let i = 0; i < all.length && picked.length < 6; i += step) {
    if (!seen.has(all[i].uri)) { picked.push(all[i]); seen.add(all[i].uri); }
  }
  return picked.slice(0, 12).sort((a, b) => (a.timestamp_ms || 0) - (b.timestamp_ms || 0));
}

function renderEvidence() {
  const items = state.evidence;
  const total = state.record?.evidence?.length || 0;
  $('#evd-sub').textContent = total
    ? `${items.length} shown of ${total} saved · click one to seek the clip`
    : 'no frames yet';
  $('#evd-strip').innerHTML = items.map((e) => {
    const refused = e.metrics?.refusal;
    return `<button type="button" class="ev ${refused ? 'flag' : ''}" data-ms="${e.timestamp_ms || 0}" data-uri="${esc(e.uri)}">
      <span class="shot"><img src="${esc(e.uri)}" alt="Overlay frame at ${esc(clock(e.timestamp_ms))}" loading="lazy"></span>
      <span class="t">${esc(clock(e.timestamp_ms))} · frame ${e.frame_index ?? '—'}</span>
      <span class="c">${esc(e.caption || e.label)}</span></button>`;
  }).join('') || '<p class="cell faint">No evidence frames were saved for this run.</p>';
  $$('#evd-strip .ev').forEach((b) => b.addEventListener('click', () => {
    seek(Number(b.dataset.ms));
    showOverlay(state.record.evidence.find((e) => e.uri === b.dataset.uri));
  }));
}

function showOverlay(ev) {
  const img = $('#ov-img');
  if (!ev) { img.hidden = true; return; }
  img.src = ev.uri;
  img.alt = `Overlay frame at ${clock(ev.timestamp_ms)}: ${ev.caption || ev.label}`;
  img.hidden = false;
  $('#ov-cap').textContent = ev.caption || ev.label;
  $('#ov-tm').textContent = `${clock(ev.timestamp_ms)} · frame ${ev.frame_index ?? '—'}${ev.metrics?.refusal ? ` · refused ${ev.metrics.refusal}` : ''}`;
}

/* ────────────────────── instruments and cost ────────────────────── */
function renderInstruments(rec) {
  const scale = rec.metrics?.scale || {};
  const q = rec.metrics?.quality || {};
  const stages = rec.timings?.stages || [];
  const totalMs = rec.timings?.total_ms || 0;
  const rate = parseFloat(($('#st-cost').textContent || '').replace(/[^0-9.]/g, '')) || 0;
  const runCost = (totalMs / 3600000) * rate;
  const counts = (rec.evidence || []).map((e) => e.metrics?.instruments?.count).filter((n) => n != null);
  const maxCount = counts.length ? Math.max(...counts) : 0;

  const gate = scale.gate || {};
  $('#in-sub').textContent = gate.passed
    ? `scale from ${String(scale.source).replace(/_/g, ' ')}, gate passed`
    : `volume withheld: ${String(gate.reason_code || 'no scale').replace(/_/g, ' ').toLowerCase()}`;

  $('#in-body').innerHTML = `
    <div class="cell"><h3>Scale</h3>
      <div class="kv"><span>Millimetres per pixel</span><span>${scale.mm_per_px != null ? `${num(scale.mm_per_px, 4)} ± ${num(scale.mm_per_px_sigma, 4)}` : 'not recovered'}</span></div>
      <div class="kv"><span>Scale gate</span><span>${esc(sentence(gate.status || 'none'))}${gate.passed ? '' : ' — volume withheld'}</span></div>
      <div class="kv"><span>Frames with a shaft scale</span><span>${gate.frames_with_scale ?? 0} of ${gate.measurable_frames ?? 0}</span></div>
      <div class="kv"><span>Scale variation across the case</span><span>${gate.robust_cv != null ? `${num(gate.robust_cv * 100, 0)}% (limit ${num((gate.max_robust_cv || 0) * 100, 0)}%)` : '—'}</span></div>
      <div class="kv"><span>Implied field width</span><span>${scale.implied_field_width_mm != null ? `${num(scale.implied_field_width_mm, 0)} mm` : '—'}</span></div>
      <div class="kv"><span>Assumed shaft</span><span>${num(scale.assumed_shaft_mm, 1)} mm</span></div>
      <div class="kv"><span>Instruments in view, peak</span><span>${maxCount}</span></div>
    </div>
    <div class="cell"><h3>Frame quality</h3>
      <div class="kv"><span>Frames read</span><span>${q.frames ?? 0}</span></div>
      <div class="kv"><span>Measurable</span><span>${q.usable ?? 0} — ${num((q.usable_fraction || 0) * 100, 1)}%</span></div>
      ${Object.entries(q.rejected_by || {}).map(([c, n]) =>
    `<div class="kv"><span>${esc(c)}</span><span>${n}</span></div>`).join('') ||
    '<div class="kv"><span>Refusals</span><span>none</span></div>'}
    </div>
    <div class="cell"><h3>Stage timings</h3>
      ${stages.map((s) => `<div class="kv"><span>${esc(s.name)} · ${s.calls} calls</span><span>${ms(s.ms)} — ${num(s.ms_per_call, 1)} ms each</span></div>`).join('')}
      <div class="kv"><span>Total</span><span>${ms(totalMs)}</span></div>
    </div>
    <div class="cell"><h3>What the run cost</h3>
      <div class="kv"><span>Instance</span><span>${esc($('#st-inst').textContent)}</span></div>
      <div class="kv"><span>Rate</span><span>${esc($('#st-cost').textContent)}</span></div>
      <div class="kv"><span>This analysis</span><span>${runCost < 0.01 ? `${(runCost * 100).toFixed(3)} cents` : `$${runCost.toFixed(4)}`}</span></div>
      <div class="kv"><span>Blood film depth assumed</span><span>${(rec.metrics?.blood?.film_depth_mm || [1, 2, 3]).join(' to ')} mm</span></div>
    </div>`;
}

function renderRail(rec) {
  const q = rec.metrics?.quality || {};
  const stages = rec.timings?.stages || [];
  const slow = stages.slice().sort((a, b) => b.ms - a.ms)[0];
  $('#st-frames').textContent = `${q.usable ?? 0} of ${q.frames ?? 0} measurable`;
  const pct = Math.round((q.usable_fraction || 0) * 100);
  $('#st-meter').className = `meter ${pct < 50 ? 'warn' : ''}`;
  $('#st-meter').firstElementChild.style.width = `${pct}%`;
  $('#st-stage').textContent = slow ? `${slow.name} ${num(slow.ms_per_call, 1)} ms/call` : 'none';
  $('#st-total').textContent = ms(rec.timings?.total_ms || 0);
  $('#st-opencv').textContent = rec.env?.opencv_version || $('#st-opencv').textContent;

  const counts = (rec.evidence || []).map((e) => e.metrics?.instruments?.count).filter((n) => n != null);
  $('#ct-live').textContent = q.usable ?? 0;
  $('#ct-trace').textContent = rec.metrics?.series?.times_ms?.length || 0;
  $('#ct-events').textContent = state.events.length;
  $('#ct-checkpoints').textContent = (state.agent?.checkpoints || []).length;
  $('#ct-instruments').textContent = counts.length ? Math.max(...counts) : 0;
  $('#ct-evidence').textContent = (rec.evidence || []).length;
}

function renderPhases(rec) {
  const p = rec.metrics?.phases;
  const host = $('#phases');
  const spans = p?.spans || [];
  if (!spans.length) { host.innerHTML = ''; return; }
  const open = openCheckpoint();
  host.setAttribute('aria-label', 'Operative phases, experimental: validated on scripted synthetic sequences only');
  host.innerHTML = spans.map((s) => {
    const now = open && open.at_ms >= s.start_ms && open.at_ms <= s.end_ms;
    return `<button type="button" class="pz seek ${now ? 'now' : 'done'}" role="listitem" data-ms="${s.start_ms}"
      style="flex:${Math.max(1, s.duration_ms)} 1 0" title="${esc(s.frames)} frames">
      <b>${esc(PHASE_NAMES[s.phase] || sentence(s.phase))}</b>${esc(clock(s.start_ms))} to ${esc(clock(s.end_ms))}${
      now ? '<i>▲ held here</i>' : ''}</button>`;
  }).join('');
  wireSeek(host);
}

/* ────────────────────────── the field trace ────────────────────────── */
function drawTrace() {
  const host = $('#trace-host');
  const rec = state.record;
  const s = rec?.metrics?.series;
  const W = Math.max(320, host.clientWidth || 720);
  const tight = W < 520;
  const H = 96, L = tight ? 48 : 58, R = 14, TOP = 8, BOT = 18;
  if (!s || !s.times_ms?.length) {
    host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="The field trace is empty until a case has been analysed.">
      <rect width="${W}" height="${H}" fill="#141F1B"/>
      <text x="${L}" y="52" font-family="Archivo" font-size="14" fill="#7F968F">The field trace draws here across the whole case, once one has run.</text></svg>`;
    state.geom = null;
    return;
  }

  const t0 = s.times_ms[0], t1 = s.times_ms[s.times_ms.length - 1] || t0 + 1;
  const span = Math.max(1, t1 - t0);
  const peak = Math.max(...s.smoothed, 0);
  // Nothing measurable: a zeroed axis would be a lie. A measured 0% is not that.
  const flat = !s.measurable.some(Boolean);
  const vmax = Math.max(0.5, peak * 1.18);
  const x0 = L, x1 = W - R, yT = TOP, yB = H - BOT;
  const X = (t) => x0 + ((t - t0) / span) * (x1 - x0);
  const Y = (v) => yB - (Math.max(0, v) / vmax) * (yB - yT);
  state.geom = { x0, x1, t0, t1, W };

  const parts = [];
  parts.push(`<rect width="${W}" height="${H}" fill="#141F1B"/>`);

  // ruled paper
  const ticks = [0, 0.5, 1];
  const rules = ticks.map((f) => `M${x0} ${Y(vmax * f).toFixed(1)}H${x1}`).join('');
  const nx = tight ? 3 : 6;
  const verticals = Array.from({ length: nx + 1 }, (_, i) =>
    `M${(x0 + ((x1 - x0) * i) / nx).toFixed(1)} ${yT}V${yB}`).join('');
  parts.push(`<g stroke="#24352F" stroke-width="1" fill="none"><path d="${rules}"/><path d="${verticals}"/></g>`);
  if (!flat) {
    parts.push(`<g font-family="Archivo" font-size="14" fill="#7F968F">${
      ticks.map((f) => `<text x="4" y="${(Y(vmax * f) + 4.5).toFixed(1)}">${num(vmax * f, 1)}%</text>`).join('')}</g>`);
  }

  // gaps, drawn before the line so the line sits on top
  let i = 0;
  while (i < s.measurable.length) {
    if (s.measurable[i]) { i += 1; continue; }
    let j = i;
    while (j + 1 < s.measurable.length && !s.measurable[j + 1]) j += 1;
    const gx0 = X(s.times_ms[i]), gx1 = Math.max(X(s.times_ms[j]), X(s.times_ms[i]) + 2);
    parts.push(`<rect x="${gx0.toFixed(1)}" y="${yT}" width="${(gx1 - gx0).toFixed(1)}" height="${yB - yT}" fill="#E8C25A" opacity=".10"/>`);
    parts.push(`<path d="M${gx0.toFixed(1)} ${yT}V${yB}M${gx1.toFixed(1)} ${yT}V${yB}" stroke="#E8C25A" stroke-width="1" opacity=".5"/>`);
    if (gx1 - gx0 > 74) {
      parts.push(`<rect x="${(gx0 + 3).toFixed(1)}" y="${yB - 21}" width="68" height="18" rx="2" fill="#E8C25A"/>`);
      parts.push(`<text x="${(gx0 + 8).toFixed(1)}" y="${yB - 7}" font-family="Archivo" font-size="14" font-weight="700" fill="#0B1210">no data</text>`);
    }
    i = j + 1;
  }

  // the line, broken where the field could not be measured
  const segments = [];
  let seg = [];
  for (let k = 0; k < s.smoothed.length; k += 1) {
    if (s.measurable[k]) seg.push(`${X(s.times_ms[k]).toFixed(1)} ${Y(s.smoothed[k]).toFixed(1)}`);
    else if (seg.length) { segments.push(seg); seg = []; }
  }
  if (seg.length) segments.push(seg);
  const d = segments.filter((g) => g.length > 1).map((g) => `M${g.join('L')}`).join(' ');
  const area = segments.filter((g) => g.length > 1).map((g) => {
    const first = g[0].split(' ')[0], last = g[g.length - 1].split(' ')[0];
    return `M${first} ${yB}L${g.join('L')}L${last} ${yB}Z`;
  }).join(' ');
  if (area) parts.push(`<path d="${area}" fill="#FF8A3D" opacity=".12"/>`);
  if (d) {
    const len = Math.round((x1 - x0) * 1.6);
    parts.push(`<path class="line" style="--len:${len}" d="${d}" fill="none" stroke="#FF8A3D" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>`);
  }

  // the onset: a vertical amber rule, its uncertainty, and a time label
  const onset = rec.metrics?.onset;
  if (onset?.detected && onset.timestamp_ms != null) {
    const ox = X(onset.timestamp_ms);
    const u = (onset.uncertainty_ms || 0) / span * (x1 - x0);
    if (u > 1) parts.push(`<rect x="${(ox - u).toFixed(1)}" y="${yT}" width="${(u * 2).toFixed(1)}" height="${yB - yT}" fill="#FF8A3D" opacity=".07"/>`);
    parts.push(`<path d="M${ox.toFixed(1)} ${yT}V${yB}" stroke="#FF8A3D" stroke-width="1.6" stroke-dasharray="4 3"/>`);
    const idx = s.times_ms.findIndex((t) => t >= onset.timestamp_ms);
    if (idx >= 0) parts.push(`<circle cx="${ox.toFixed(1)}" cy="${Y(s.smoothed[idx]).toFixed(1)}" r="4" fill="#FF8A3D"/>`);
    const label = `onset ${clock(onset.timestamp_ms)} ± ${num(onset.uncertainty_ms / 1000, 0)} s`;
    const w = 20 + label.length * 7.6;
    const lx = Math.max(x0 + 2, ox + w + 8 > x1 ? ox - w - 6 : ox + 6);
    // The caption owns the top-left corner, so a label that would land on it
    // drops to the second row rather than printing through it.
    const ly = lx < x0 + 158 ? yT + 21 : yT;
    parts.push(`<rect x="${lx.toFixed(1)}" y="${ly}" width="${w.toFixed(1)}" height="19" rx="2" fill="#FF8A3D"/>`);
    parts.push(`<text x="${(lx + 8).toFixed(1)}" y="${ly + 14}" font-family="Archivo" font-size="14" font-weight="700" fill="#0B1210">${esc(label)}</text>`);
  }

  parts.push(`<text x="${x0 + 6}" y="${yT + 14}" font-family="Archivo" font-size="14" fill="#9DB3AC">Blood-covered field, % of view</text>`);
  if (flat) {
    parts.push(`<text x="${((x0 + x1) / 2).toFixed(1)}" y="${((yT + yB) / 2 + 5).toFixed(1)}" text-anchor="middle"
      font-family="Archivo" font-size="14" font-weight="600" fill="#E8C25A">No frame in this clip could be measured, so the trace carries no line</text>`);
  }
  const labels = Array.from({ length: nx + 1 }, (_, k) => t0 + (span * k) / nx);
  parts.push(`<g font-family="Archivo" font-size="14" fill="#7F968F">${
    labels.map((t, k) => {
      const x = X(t);
      const anchor = k === 0 ? 'start' : k === nx ? 'end' : 'middle';
      return `<text x="${x.toFixed(1)}" y="${H - 4}" text-anchor="${anchor}">${clock(t)}</text>`;
    }).join('')}</g>`);

  const summary = `The field trace: share of the visible field covered in blood from ${clock(t0)} to ${clock(t1)}, peak ${num(peak, 1)} per cent${
    onset?.detected ? `, onset marked at ${clock(onset.timestamp_ms)}` : ', no onset detected'}.`;
  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(summary)}">${parts.join('')}</svg>`;
}

function onPlayhead() {
  const video = $('#video');
  const cursor = $('#trace-cursor');
  if (!state.geom || !video.src) { cursor.style.display = 'none'; return; }
  const t = state.cursorMs;
  const { x0, x1, t0, t1, W } = state.geom;
  const host = $('#trace-host');
  const scale = (host.clientWidth || W) / W;
  const x = (x0 + ((Math.min(Math.max(t, t0), t1) - t0) / Math.max(1, t1 - t0)) * (x1 - x0)) * scale;
  cursor.style.display = 'block';
  cursor.style.left = `${x.toFixed(1)}px`;

  const bar = $('#vidbar');
  const dur = state.record?.metrics?.video?.duration_ms;
  const open = state.agent?.open_checkpoint;
  bar.hidden = false;
  bar.innerHTML = `<span class="rec ${isUnmeasurableNow(t) ? 'warn' : ''}"></span>${
    isUnmeasurableNow(t) ? 'Not measurable at this frame' : 'Measured at this frame'}
    <span style="margin-left:auto">${esc(clock(t))} / ${esc(clock(dur))}${open ? ' · step held' : ''}</span>`;

  const nearest = nearestEvidence(t);
  if (nearest) {
    if (!$('#ov-img').src.endsWith(nearest.uri)) showOverlay(nearest);
    if (!state.decodable) {
      const big = $('#field-img');
      if (!big.src.endsWith(nearest.uri)) {
        big.src = nearest.uri;
        big.alt = `The field at ${clock(nearest.timestamp_ms)}: ${nearest.caption || nearest.label}`;
      }
    }
  }
}

function isUnmeasurableNow(t) {
  const s = state.record?.metrics?.series;
  if (!s?.times_ms?.length) return false;
  let best = 0, bestD = Infinity;
  s.times_ms.forEach((tm, k) => { const d = Math.abs(tm - t); if (d < bestD) { bestD = d; best = k; } });
  return !s.measurable[best];
}

function nearestEvidence(t) {
  const all = state.record?.evidence || [];
  if (!all.length) return null;
  let best = null, bestD = Infinity;
  all.forEach((e) => {
    const d = Math.abs((e.timestamp_ms ?? 0) - t);
    if (d < bestD) { bestD = d; best = e; }
  });
  return best;
}

/* ────────────────────── nav highlighting ────────────────────── */
function watchSections() {
  const map = {
    'live-field': 'live', 'field-trace': 'trace', events: 'events',
    checkpoints: 'checkpoints', instruments: 'instruments', evidence: 'evidence',
  };
  const links = $$('.nav a');
  const setActive = (key) => links.forEach((a) => a.classList.toggle('on', a.dataset.nav === key));
  setActive('live');
  const observer = new IntersectionObserver((entries) => {
    const visible = entries.filter((e) => e.isIntersecting)
      .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
    if (visible) setActive(map[visible.target.id]);
  }, { rootMargin: '-80px 0px -55% 0px', threshold: 0.01 });
  Object.keys(map).forEach((id) => { const el = document.getElementById(id); if (el) observer.observe(el); });

  $('.nav a[data-nav="checkpoints"]').addEventListener('click', (e) => {
    const card = $('#checkpoint-card').hidden ? ($('#checkpoint-resolved').hidden ? null : $('#checkpoint-resolved')) : $('#checkpoint-card');
    if (card) { e.preventDefault(); card.scrollIntoView({ block: 'center' }); }
  });
}

boot();
