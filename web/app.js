'use strict';
const $ = id => document.getElementById(id);
let token = '', runs = [], selected = '', rendered = '', lastResult = '', busy = false, submitting = false;
const time = value => {
  const seconds = Math.floor(value);
  return seconds >= 3600
    ? `${Math.floor(seconds / 3600)}:${String(Math.floor(seconds / 60) % 60).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
    : `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
};
function showError(id, message) { $(id).textContent = message; $(id).hidden = !message; }
async function request(path, data) {
  const response = await fetch(path, data === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json', 'X-Clipper-Token': token}, body: JSON.stringify(data)
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'The action failed. Please retry.');
  return result;
}
function renderRun() {
  const run = runs.find(item => item.id === selected);
  const key = run ? `${run.id}:${run.revision}` : '';
  if (key === rendered) return;
  rendered = key;
  $('clips').replaceChildren();
  $('open-folder').disabled = !run;
  $('clip-count').textContent = run ? run.clips.length : 0;
  $('selection-mode').textContent = run ? (run.combat_only ? 'Confirmed eliminations' : 'Audio-only · legacy') : '—';
  const notices = [];
  if (run && !run.combat_only) notices.push('These older drafts used audio-only selection. For fight clips, generate a new run above.');
  if (run?.status === 'failed') notices.push(`This run did not finish. Completed clips are still available. ${run.error || ''}`);
  if (run?.status === 'created') notices.push('This run is in progress or was interrupted. Only completed clips appear below.');
  if (run?.warnings?.length) notices.push('Some speech could not be transcribed reliably. Check the caption note on each clip.');
  showError('run-notice', notices.join('\n'));
  $('empty').hidden = !!run?.clips.length;
  $('empty').textContent = run ? 'No completed clips in this run. Check progress above or try another replay.' : 'Your clips will appear here. Paste a replay above to get started.';
  for (const [index, clip] of (run?.clips || []).entries()) {
    const card = $('clip-template').content.cloneNode(true);
    const video = card.querySelector('video');
    video.src = `${clip.url}?v=${run.revision}#t=0.1`;
    video.setAttribute('aria-label', `Preview clip ${index + 1}, source ${time(clip.start)} to ${time(clip.end)}`);
    card.querySelector('h3').textContent = `Clip ${String(index + 1).padStart(2, '0')}`;
    card.querySelector('.duration').textContent = `${Math.round(clip.end - clip.start)} sec`;
    card.querySelector('.interval').textContent = `Source ${time(clip.start)} – ${time(clip.end)}`;
    card.querySelector('.caption-note').textContent = clip.captions ? 'Draft captions · review for accuracy' : 'Speech captions omitted · original audio retained';
    const editor = card.querySelector('.headline-form');
    const input = editor.querySelector('input');
    input.value = clip.headline || '';
    input.setAttribute('aria-label', `Top headline for clip ${index + 1}`);
    editor.addEventListener('submit', async event => {
      event.preventDefault();
      if (busy || submitting || !token) return;
      submitting = true;
      const errorText = editor.querySelector('.headline-error');
      errorText.hidden = true;
      editor.querySelector('button').disabled = true;
      try { await request('/api/headline', {run: run.id, clip: clip.name, headline: input.value}); }
      catch (error) { errorText.textContent = error.message; errorText.hidden = false; }
      finally { submitting = false; await refresh(); }
    });
    const link = card.querySelector('a');
    link.href = `${clip.url}?download=1`;
    link.download = `${run.source_id}_${clip.name}`;
    $('clips').append(card);
  }
}
async function refresh() {
  try {
    const state = await request('/api/state');
    token = state.token;
    runs = state.runs;
    busy = state.job.status === 'running';
    showError('connection', state.missing.length ? `Setup needed: ${state.missing.join(', ')} is missing. Follow the setup instructions in README, then restart Clipper.` : '');
    $('generate').disabled = busy || submitting || !!state.missing.length;
    $('generate').textContent = busy ? 'Processing…' : 'Generate clips ↗';
    const labels = {idle: 'Ready', running: 'Working', complete: 'Finished', failed: 'Failed'};
    $('job-badge').textContent = labels[state.job.status] || state.job.status;
    $('job-badge').classList.toggle('active', busy);
    const log = state.job.log;
    $('progress-log').textContent = log.join('\n') || 'Progress will appear here.';
    const stage = [...log].reverse().find(line => /^(validate:|download:|analyze:|combat:|select:|transcribe:|render:)/.test(line));
    const result = runs.find(run => run.id === state.job.result_run);
    const stageLabel = !stage ? (state.job.kind === 'headline' ? 'Updating the clip headline…' : 'Starting replay processing…')
      : stage.startsWith('validate:') ? 'Checking the replay…'
      : stage.startsWith('download:') ? 'Downloading or reusing the replay…'
      : /^(analyze:|combat:)/.test(stage) ? 'Finding confirmed elimination moments…'
      : stage.startsWith('select:') ? 'Choosing distinct clips…'
      : stage.startsWith('transcribe:') ? 'Preparing speech captions…' : 'Rendering clips…';
    $('job-message').textContent = busy ? stageLabel
      : state.job.status === 'failed' ? 'Processing stopped. Expand recent progress for the error, then retry.'
      : state.job.status === 'complete' ? (state.job.kind === 'headline' ? 'Headline updated. Preview or download the refreshed clip.' : `${result?.clips.length || 0} clips ready. ${result?.clips.length ? 'Review them below.' : 'No moments met the selection requirements.'}`)
      : 'Ready for your next stream.';
    if (busy || state.job.status === 'failed') $('progress-details').open = true;
    if (state.job.result_run && state.job.result_run !== lastResult && !busy) {
      selected = state.job.result_run; lastResult = selected;
    }
    if (!runs.some(run => run.id === selected)) selected = (runs.find(run => run.combat_only) || runs[0])?.id || '';
    const options = runs.map(run => `${run.id}:${run.clips.length}:${run.status}`).join('|');
    if ($('run-select').dataset.options !== options) {
      $('run-select').replaceChildren();
      for (const run of runs) {
        const option = document.createElement('option');
        option.value = run.id;
        option.textContent = `${run.source_id} · ${run.combat_only ? 'Combat' : 'Audio-only'} · ${run.clips.length} clips · ${run.id.slice(-6)}`;
        $('run-select').append(option);
      }
      if (!runs.length) $('run-select').append(new Option('No runs yet', ''));
      $('run-select').dataset.options = options;
    }
    $('run-select').disabled = !runs.length;
    $('run-select').value = selected;
    renderRun();
    document.querySelectorAll('.headline-button').forEach(button => { button.disabled = busy || submitting; });
  } catch (error) {
    $('generate').disabled = true;
    showError('connection', `Cannot reach Clipper. Keep the launcher window open or relaunch it. ${error.message}`);
  }
}
$('generate-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || submitting || !token) return;
  submitting = true; $('generate').disabled = true;
  showError('form-error', '');
  try {
    await request('/api/start', {url: $('replay-url').value.trim(), max_clips: Number($('max-clips').value)});
  } catch (error) { showError('form-error', error.message); }
  finally { submitting = false; await refresh(); }
});
$('run-select').addEventListener('change', event => { selected = event.target.value; renderRun(); });
$('open-folder').addEventListener('click', async () => {
  try { await request('/api/open-folder', {run: selected}); }
  catch (error) { showError('run-notice', error.message); }
});
// Poll only after the previous request finishes; leave video elements intact while playing.
async function poll() { await refresh(); setTimeout(poll, 2000); }
poll();
