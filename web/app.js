'use strict';
const $ = id => document.getElementById(id);
let token = '', runs = [], selected = '', rendered = '', lastResult = '', busy = false, submitting = false;
let downloadKey = '';
let publishClip = null, publishing = null, historyKey = '', reviewId = '';
const historyPages = new Map();
const historyPageSize = 5;
const time = value => {
  const seconds = Math.floor(value);
  return seconds >= 3600
    ? `${Math.floor(seconds / 3600)}:${String(Math.floor(seconds / 60) % 60).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
    : `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
};
function showError(id, message) { $(id).textContent = message; $(id).hidden = !message; }
function batchLabel(run) {
  const date = new Date(run.batch_date * 1000).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric'
  });
  return `${date} · ${run.id.slice(-6)}`;
}
function showBatchSource(element, run) {
  element.textContent = run.source_label;
  if (run.source_url && /^[\w-]{11}$/.test(run.source_id)) {
    const link = document.createElement('a');
    link.href = `https://www.youtube.com/watch?v=${run.source_id}`;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = 'Open source stream ↗';
    element.append(' · ', link);
  }
}
function renderStoryReview(run) {
  $('story-review').hidden = !run?.stories?.length;
  $('story-cuts').replaceChildren();
  showError('story-error', '');
  for (const [index, story] of (run?.stories || []).entries()) {
    const row = document.createElement('fieldset');
    const legend = document.createElement('legend');
    legend.textContent = story.summary;
    const pickLabel = document.createElement('label');
    const pick = document.createElement('input');
    pick.type = 'checkbox';
    pick.checked = story.complete;
    pickLabel.append(pick, story.complete ? ' Render this story' : ' Render this story · ending unconfirmed');
    const notes = document.createElement('p');
    notes.className = 'help';
    notes.textContent = `${time(story.start)}–${time(story.end)} · ${story.start_reason} ${story.end_reason}${story.visual_evidence ? ` Gameplay check: ${story.visual_evidence}` : ''}`;
    row.append(legend, pickLabel, notes);
    if (run.source_url && /^[\w-]{11}$/.test(run.source_id)) {
      const link = document.createElement('a');
      link.href = `https://www.youtube.com/watch?v=${run.source_id}&t=${Math.floor(story.start)}s`;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = 'Check this moment in the stream ↗';
      row.append(link);
    }
    const bounds = document.createElement('div');
    bounds.className = 'story-bounds';
    for (const field of ['start', 'end']) {
      const label = document.createElement('label');
      label.textContent = field === 'start' ? 'Start (seconds)' : 'End (seconds)';
      const input = document.createElement('input');
      input.type = 'number';
      input.min = 0;
      input.max = run.duration;
      input.step = 'any';
      input.name = field;
      input.value = story[field];
      label.append(input);
      bounds.append(label);
    }
    row.dataset.index = index;
    row.append(bounds);
    $('story-cuts').append(row);
  }
}
$('story-review').addEventListener('submit', async event => {
  event.preventDefault();
  const run = runs.find(item => item.id === selected);
  if (!run || busy || submitting || !token) return;
  const cuts = [...$('story-cuts').querySelectorAll('fieldset')]
    .filter(row => row.querySelector('[type=checkbox]').checked)
    .map(row => ({index: Number(row.dataset.index), start: row.querySelector('[name=start]').valueAsNumber,
      end: row.querySelector('[name=end]').valueAsNumber}));
  showError('story-error', '');
  submitting = true;
  $('render-stories').disabled = true;
  try { await request('/api/story-render', {run: run.id, revision: run.revision, cuts}); }
  catch (error) { showError('story-error', error.message); }
  finally { submitting = false; await refresh(); }
});
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
  renderStoryReview(run);
  $('open-folder').disabled = !run;
  $('batch-source').hidden = !run;
  if (run) showBatchSource($('batch-source'), run);
  $('clip-count').textContent = run ? run.clips.length : 0;
  $('selection-mode').textContent = run ? (run.story_mode ? 'Transcript & gameplay' : run.combat_only ? 'Confirmed eliminations' : 'Audio peaks') : '—';
  const notices = [];
  if (run?.game === 'gta6' && !run.story_mode) notices.push('This batch used audio peaks. Review the action and reactions before posting.');
  else if (run?.game === 'fortnite' && !run.combat_only) notices.push('These older drafts used audio-only selection. For fight clips, generate a new run above.');
  if (run?.error) notices.push(run.error);
  if (run?.status === 'created') notices.push('This run is in progress or was interrupted. Only completed clips appear below.');
  if (run?.warnings?.length) notices.push(...run.warnings);
  showError('run-notice', notices.join('\n'));
  $('empty').hidden = !!(run?.clips.length || run?.stories?.length);
  $('empty').textContent = run?.status === 'no_stories' ? 'No matching stories were found. Try a different stream brief.'
    : run ? 'No completed clips in this run. Check progress above or try another replay.' : 'Your clips will appear here. Paste a replay above to get started.';
  for (const [index, clip] of (run?.clips || []).entries()) {
    const card = $('clip-template').content.cloneNode(true);
    const video = card.querySelector('video');
    video.poster = `${clip.poster}?v=${run.revision}`;
    video.src = `${clip.url}?v=${run.revision}`;
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
    card.querySelector('.publish-clip').addEventListener('click', () => selectPublishClip(run, clip));
    $('clips').append(card);
  }
}
const sourceMode = () => document.querySelector('input[name="source-mode"]:checked').value;
function updateSourceMode() {
  const live = sourceMode() === 'live';
  $('replay-source').hidden = live;
  $('live-source').hidden = !live;
  $('replay-url').disabled = live;
  $('live-url').disabled = !live;
  $('live-url').required = live;
  if (!busy) $('generate').textContent = live ? 'Start monitoring →' :
    $('game').value === 'gta6' ? 'Find story cuts →' : 'Generate clips ↗';
}
document.querySelectorAll('input[name="source-mode"]').forEach(input => input.addEventListener('change', updateSourceMode));
updateSourceMode();
$('stop-live').addEventListener('click', async () => {
  $('stop-live').disabled = true;
  try { await request('/api/live/stop', {}); }
  catch (error) { showError('form-error', error.message); }
  finally { $('stop-live').disabled = false; await refresh(); }
});
async function refresh() {
  try {
    const state = await request('/api/state');
    token = state.token;
    runs = state.runs;
    busy = state.job.status === 'running';
    const missing = [...state.missing, ...($('game').value === 'fortnite' ? state.combat_missing : [])];
    showError('connection', missing.length ? `Setup needed: ${missing.join(', ')} is missing. Follow the setup instructions in README, then restart Clipper.` : '');
    $('generate').disabled = busy || submitting || !!missing.length;
    $('render-stories').disabled = busy || submitting;
    if (busy) $('generate').textContent = 'Working…';
    else updateSourceMode();
    $('stop-live').hidden = !busy || state.job.kind !== 'live';
    const labels = {idle: 'Ready', running: 'Working', complete: 'Finished', failed: 'Failed', cancelled: 'Stopped'};
    $('job-badge').textContent = labels[state.job.status] || state.job.status;
    $('job-badge').classList.toggle('active', busy);
    const log = state.job.log;
    $('progress-details').hidden = state.job.kind === 'publish';
    $('progress-log').textContent = state.job.kind === 'publish' ? '' : (log.join('\n') || 'Progress will appear here.');
    const stage = [...log].reverse().find(line => /^(live:|audience:|validate:|download:|analyze:|combat:|select:|story:|transcribe:|title:|render:|upload:)/.test(line));
    const result = runs.find(run => run.id === state.job.result_run);
    const stageLabel = state.job.kind === 'publish' ? 'Publishing clips… Follow each clip in Upload history.'
      : !stage ? (state.job.kind === 'headline' ? 'Updating the clip headline…' : 'Starting replay processing…')
      : stage.startsWith('live:') || stage.startsWith('audience:') ? stage.split(': ').slice(1).join(': ')
      : stage.startsWith('validate:') ? 'Checking the replay…'
      : stage.startsWith('download: using validated saved replay') ? 'Reusing saved replay; download skipped.'
      : stage.startsWith('download:') ? 'Downloading the replay…'
      : /^(analyze:|combat:)/.test(stage) ? 'Finding highlight moments…'
      : stage.startsWith('select:') ? 'Choosing distinct clips…'
      : stage.startsWith('title:') ? 'Writing a title from the clip’s action…'
      : stage.startsWith('story:') ? stage.slice(7)
      : stage.startsWith('transcribe:') ? stage.slice(12) : 'Rendering clips…';
    $('job-message').textContent = busy ? stageLabel
      : state.job.status === 'failed' ? (state.job.kind === 'publish' ? 'An upload needs attention. Check each destination in upload history.' : 'Processing stopped. Expand recent progress for the error, then retry.')
      : state.job.status === 'complete' ? (state.job.kind === 'publish' ? 'Upload finished. Open the saved links in upload history.' : state.job.kind === 'headline' ? 'Headline updated. Preview or download the refreshed clip.' : result?.stories?.length ? `${result.stories.length} proposed cuts. Review them before rendering.` : `${result?.clips.length || 0} clips ready. ${result?.clips.length ? 'Review them below.' : 'No moments met the selection requirements.'}`)
      : state.job.status === 'cancelled' ? 'Live job stopped.' : 'Ready for your next stream.';
    if (busy || state.job.status === 'failed') $('progress-details').open = true;
    if (state.job.result_run && state.job.result_run !== lastResult && !busy) {
      selected = state.job.result_run; lastResult = selected;
    }
    if (!runs.some(run => run.id === selected)) selected = runs[0]?.id || '';
    const options = JSON.stringify(runs.map(run => [run.id, run.source_label, run.clips.length, run.stories?.length, run.batch_date]));
    if ($('run-select').dataset.options !== options) {
      $('run-select').replaceChildren();
      const streams = new Map();
      for (const run of runs) {
        if (!streams.has(run.source_id)) {
          const stream = document.createElement('optgroup');
          stream.label = run.source_label;
          streams.set(run.source_id, stream);
          $('run-select').append(stream);
        }
        const option = document.createElement('option');
        option.value = run.id;
        const count = run.stories?.length ? `${run.stories.length} to review` : `${run.clips.length} clips`;
        option.textContent = `${batchLabel(run)} · ${run.game === 'gta6' ? 'GTA 6' : 'Fortnite'} · ${count}`;
        streams.get(run.source_id).append(option);
      }
      if (!runs.length) $('run-select').append(new Option('No batches yet', ''));
      $('run-select').dataset.options = options;
    }
    $('run-select').disabled = !runs.length;
    $('run-select').value = selected;
    renderRun();
    document.querySelectorAll('.headline-button').forEach(button => { button.disabled = busy || submitting; });
    publishing = state.publishing;
    renderPublishing();
    renderDownloads(state.downloads || []);
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
    await request('/api/start', {url: $(sourceMode() === 'live' ? 'live-url' : 'replay-url').value.trim(), mode: sourceMode(), max_clips: Number($('max-clips').value), game: $('game').value, new_moments: $('new-moments').checked, story_brief: $('story-brief').value.trim()});
  } catch (error) { showError('form-error', error.message); }
  finally { submitting = false; await refresh(); }
});
function updateGameHelp() {
  $('story-brief-field').hidden = $('game').value !== 'gta6';
  updateSourceMode();
  $('game-help').textContent = $('game').value === 'gta6'
    ? 'Review transcript-led story cuts before rendering. Use a brief to focus on a topic.'
    : 'Confirmed eliminations only. Fewer clips may qualify than your limit.';
}
try {
  const savedGame = localStorage.getItem('clipper-game');
  if (savedGame === 'fortnite' || savedGame === 'gta6') $('game').value = savedGame;
} catch {}
updateGameHelp();
$('game').addEventListener('change', () => {
  try { localStorage.setItem('clipper-game', $('game').value); } catch {}
  updateGameHelp();
  refresh();
});
$('run-select').addEventListener('change', event => { selected = event.target.value; renderRun(); renderPublishing(); });
$('open-folder').addEventListener('click', async () => {
  try { await request('/api/open-folder', {run: selected}); }
  catch (error) { showError('run-notice', error.message); }
});
function selectPublishClip(run, clip) {
  publishClip = {run: run.id, name: clip?.name, revision: run.revision};
  $('composer-heading').textContent = clip ? 'Prepare your post' : 'Prepare a batch';
  $('batch-clip-picker').hidden = !!clip;
  $('batch-clip-list').replaceChildren();
  if (!clip) {
    for (const item of run.clips) {
      const label = document.createElement('label');
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.value = item.name;
      input.checked = true;
      label.append(input, `${item.name} · ${item.headline || item.title}`);
      $('batch-clip-list').append(label);
    }
  }
  $('publish-preview').pause();
  $('publish-preview').parentElement.hidden = !clip;
  $('single-youtube-fields').hidden = !clip;
  $('single-instagram-fields').hidden = !clip;
  $('publish-empty').hidden = true;
  $('publish-form').hidden = false;
  if (clip) {
    $('publish-preview').poster = `${clip.poster}?v=${run.revision}`;
    $('publish-preview').src = `${clip.url}?v=${run.revision}`;
  }
  $('publish-selection').textContent = clip ? `${clip.name} · ${run.source_id} · ${time(clip.start)}–${time(clip.end)}` : `${run.clips.length} clips · ${run.source_id} · Each clip uses its own saved title and description.`;
  $('post-title').value = clip?.title || '';
  $('post-description').value = clip?.description || '';
  $('post-caption').value = clip?.reel_caption || '';
  $('post-audience').value = '';
  showError('publish-error', '');
  $('publishing').scrollIntoView({behavior: 'smooth'});
  $(clip ? 'post-title' : 'post-youtube').focus({preventScroll: true});
}
$('publish-all').addEventListener('click', () => {
  const run = runs.find(item => item.id === selected);
  if (run?.clips.length) selectPublishClip(run);
});
async function publishAction(action, data) {
  if (busy || submitting || !token) throw new Error('Wait for the current job to finish.');
  submitting = true;
  renderPublishing();
  try { return await request(`/api/publish/${action}`, data); }
  finally { submitting = false; await refresh(); }
}
function renderPublishing() {
  if (!publishing) return;
  const connections = publishing.connections;
  for (const platform of ['youtube', 'instagram', 'storage']) {
    const account = connections[platform];
    $(platform + '-status').textContent = account
      ? platform === 'storage' ? `Configured · ${account.bucket}` : `Connected · @${account.handle}`
      : platform === 'storage' ? 'Not configured' : 'Not connected';
    const disconnect = document.querySelector(`.disconnect[data-platform="${platform}"]`);
    disconnect.hidden = !account;
  }
  if (publishing.setup_error || publishing.connection_error) showError('publish-error', publishing.setup_error || publishing.connection_error);
  const disabled = busy || submitting || !!publishing.setup_error;
  document.querySelectorAll('.account-form button,.disconnect,.publish-clip,#review-upload,#upload-now,.resume-upload').forEach(button => { button.disabled = disabled; });
  $('publish-all').disabled = disabled || !runs.find(run => run.id === selected)?.clips.length;
  $('retry-reels').disabled = disabled;
  $('retry-reels').hidden = !publishing.history.some(item => item.target === 'instagram' && ['failed', 'interrupted'].includes(item.status));
  const openLogs = new Set([...$('upload-history').querySelectorAll('details[open]')].map(el => el.dataset.upload));
  const key = JSON.stringify([publishing.history, disabled, runs.map(run => run.revision)]);
  if (key === historyKey) return;
  historyKey = key;
  $('upload-history').replaceChildren();
  if (!publishing.history.length) {
    const empty = document.createElement('p'); empty.className = 'help'; empty.textContent = 'No uploads yet.';
    $('upload-history').append(empty);
  }
  const batches = new Map();
  for (const item of publishing.history) {
    if (!batches.has(item.run)) batches.set(item.run, new Map());
    const groups = batches.get(item.run);
    const groupKey = `${item.name}/${item.sha}`;
    if (!groups.has(groupKey)) groups.set(groupKey, []);
    groups.get(groupKey).push(item);
  }
  for (const [id, grouped] of batches) {
    const run = runs.find(run => run.id === id);
    const batch = document.createElement('section');
    const heading = document.createElement('h3');
    heading.textContent = run ? `Batch · ${batchLabel(run)}` : id;
    batch.append(heading);
    if (run) {
      const source = document.createElement('p');
      source.className = 'help';
      showBatchSource(source, run);
      batch.append(source);
    }
    const clips = [...grouped.values()];
    const pageCount = Math.ceil(clips.length / historyPageSize);
    let page = Math.min(historyPages.get(id) || 0, pageCount - 1);
    const list = document.createElement('div');
    batch.append(list);
    const previous = document.createElement('button');
    const next = document.createElement('button');
    const pageLabel = document.createElement('span');
    function renderPage() {
      const start = page * historyPageSize;
      list.replaceChildren();
      for (const items of clips.slice(start, start + historyPageSize)) {
        const group = document.createElement('article'); group.className = 'panel upload-group';
        const clipHeading = document.createElement('h4');
        const {name} = items[0];
        clipHeading.textContent = run?.clips.find(clip => clip.name === name)?.headline || name;
        const label = document.createElement('p'); label.className = 'help'; label.textContent = name;
        group.append(clipHeading, label);
        for (const item of items) group.append(uploadHistoryRow(item, disabled, openLogs));
        list.append(group);
      }
      pageLabel.textContent = `Page ${page + 1} of ${pageCount} · ${clips.length} clips`;
      previous.disabled = page === 0;
      next.disabled = page === pageCount - 1;
    }
    if (pageCount > 1) {
      const pagination = document.createElement('nav');
      pagination.className = 'history-pagination';
      pagination.setAttribute('aria-label', `Upload history for ${heading.textContent}`);
      pageLabel.setAttribute('aria-live', 'polite');
      pageLabel.className = 'help';
      for (const [button, label, direction] of [[previous, 'Previous', -1], [next, 'Next', 1]]) {
        button.type = 'button';
        button.textContent = label;
        button.addEventListener('click', () => {
          page += direction;
          historyPages.set(id, page);
          renderPage();
          if (button.disabled) (direction > 0 ? previous : next).focus();
        });
      }
      pagination.append(previous, pageLabel, next);
      batch.append(pagination);
    }
    renderPage();
    $('upload-history').append(batch);
  }
}
function uploadHistoryRow(item, disabled, openLogs) {
  const row = document.createElement('div'); row.className = 'upload-row';
  const details = document.createElement('div');
  const title = document.createElement('h3'); title.textContent = `${item.target === 'youtube' ? 'YouTube' : 'Instagram'} · @${item.handle}`;
  const status = document.createElement('p'); status.className = 'help';
  status.textContent = `${item.status}${item.target === 'youtube' ? ` · ${item.progress}%` : ''}${item.visibility ? ` · ${item.visibility}` : ''}${item.cleanup_pending ? ' · temporary storage copy remains' : ''}`;
  const bar = document.createElement('progress');
  bar.max = 100;
  bar.setAttribute('aria-label', `${item.target} progress for ${item.name}`);
  if (item.target !== 'instagram' || item.status !== 'uploading') bar.value = item.progress;
  details.append(title, status, bar);
  if (item.log?.length) {
    const log = document.createElement('details'); log.dataset.upload = item.id;
    log.open = openLogs.has(item.id);
    const summary = document.createElement('summary'); summary.textContent = 'Activity log';
    const lines = document.createElement('ol');
    for (const event of item.log) {
      const line = document.createElement('li');
      line.textContent = `${new Date(event.time * 1000).toLocaleTimeString()} · ${event.stage}`;
      lines.append(line);
    }
    log.append(summary, lines); details.append(log);
  }
  if (item.error) { const error = document.createElement('p'); error.className = 'error-text'; error.textContent = item.error; details.append(error); }
  const actions = document.createElement('div'); actions.className = 'upload-actions';
  if (item.url) { const link = document.createElement('a'); link.href = item.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = item.account_link ? 'Open account ↗' : 'Open video ↗'; actions.append(link); }
  if (!['uploaded', 'published'].includes(item.status) || item.cleanup_pending) {
    const button = document.createElement('button'); button.className = 'resume-upload'; button.disabled = disabled;
    button.textContent = ['uploaded', 'published'].includes(item.status) ? 'Retry cleanup' : 'Review & resume';
    button.addEventListener('click', async () => {
      try { openReview(await publishAction('retry-review', {id: item.id})); }
      catch (error) { showError('publish-error', error.message); }
    }); actions.append(button);
  }
  row.append(details, actions);
  return row;
}
function postingFields() {
  $('youtube-fields').hidden = !$('post-youtube').checked;
  $('instagram-fields').hidden = !$('post-instagram').checked;
}
$('retry-reels').addEventListener('click', async () => {
  try { openReview(await publishAction('retry-reels', {})); }
  catch (error) { showError('publish-error', error.message); }
});
for (const id of ['post-youtube', 'post-instagram']) $(id).addEventListener('change', postingFields);
postingFields();
$('youtube-connect').addEventListener('submit', async event => {
  event.preventDefault(); showError('publish-error', '');
  // Open synchronously so browser popup protection does not interrupt OAuth.
  const popup = window.open('about:blank', '_blank');
  try {
    const file = $('google-config').files[0];
    if (!file || file.size > 60000) throw new Error('Choose the Desktop OAuth JSON file (up to 60 KB).');
    await publishAction('youtube-config', {config: JSON.parse(await file.text())});
    const result = await publishAction('youtube-connect', {});
    if (popup) { popup.opener = null; popup.location.href = result.url; }
    else window.location.assign(result.url);
  } catch (error) { if (popup) popup.close(); showError('publish-error', error.message); }
  finally { $('google-config').value = ''; }
});
for (const platform of ['instagram', 'storage']) {
  $(platform + '-connect').addEventListener('submit', async event => {
    event.preventDefault(); showError('publish-error', '');
    const form = event.currentTarget;
    try { await publishAction(platform + '-connect', Object.fromEntries(new FormData(form))); }
    catch (error) { showError('publish-error', error.message); }
    finally { form.querySelectorAll('input[type=password]').forEach(input => { input.value = ''; }); }
  });
}
document.querySelectorAll('.disconnect').forEach(button => button.addEventListener('click', async () => {
  try { await publishAction('disconnect', {platform: button.dataset.platform}); }
  catch (error) { showError('publish-error', error.message); }
}));
$('publish-form').addEventListener('submit', async event => {
  event.preventDefault(); showError('publish-error', '');
  if (!publishClip) return;
  try {
    if ($('post-youtube').checked && !$('post-audience').value) throw new Error('Choose whether the YouTube video is made for kids.');
    const run = runs.find(item => item.id === publishClip.run);
    if (!run || run.revision !== publishClip.revision) throw new Error('This clip was edited. Choose Publish on its refreshed preview before reviewing.');
    openReview(await publishAction(publishClip.name ? 'prepare' : 'prepare-batch', {run: publishClip.run, clip: publishClip.name, revision: publishClip.revision,
      clips: publishClip.name ? undefined : [...$('batch-clip-list').querySelectorAll('input:checked')].map(input => input.value),
      youtube: $('post-youtube').checked, instagram: $('post-instagram').checked,
      title: $('post-title').value, description: $('post-description').value, caption: $('post-caption').value,
      privacy: $('post-privacy').value, made_for_kids: $('post-audience').value === 'yes'}));
  } catch (error) { showError('publish-error', error.message); }
});
function openReview(review) {
  reviewId = review.review_id;
  $('review-preview').hidden = !!review.clips;
  if (review.clips) {
    $('review-clip').textContent = `${review.clips.length} clips · select a preview to check its footage and posting details`;
    $('review-details').replaceChildren();
    for (const clip of review.clips) {
      const group = document.createElement('details'); group.className = 'batch-review-clip';
      const title = document.createElement('summary');
      title.textContent = `${clip.name} · ${clip.meta.title}`;
      const preview = document.createElement('video');
      preview.controls = true; preview.playsInline = true; preview.preload = 'none';
      group.addEventListener('toggle', () => {
        if (group.open && !preview.hasAttribute('src')) preview.src = clip.preview;
        if (!group.open) preview.pause();
      });
      group.append(title, preview);
      for (const target of clip.destinations) group.append(reviewDestination(clip, target));
      $('review-details').append(group);
    }
    showError('review-error', '');
    $('upload-now').textContent = review.retry ? 'Resume failed Reels' : 'Publish batch';
    $('upload-review').showModal();
    return;
  }
  $('review-clip').textContent = `${review.name} · ${Math.round(review.duration)} sec · version ${review.sha}`;
  $('review-preview').src = review.preview + '#t=0.1';
  $('review-details').replaceChildren();
  for (const target of review.destinations) $('review-details').append(reviewDestination(review, target));
  showError('review-error', '');
  $('upload-now').textContent = review.retry ? 'Resume saved action' : 'Upload now';
  $('upload-review').showModal();
}
function reviewDestination(review, target) {
    const section = document.createElement('section');
    const heading = document.createElement('h3'); heading.textContent = `${target.target === 'youtube' ? 'YouTube' : 'Instagram'} · @${target.handle}`;
    const text = document.createElement('p');
    text.textContent = target.target === 'youtube'
      ? `${review.meta.title}\n\n${review.meta.description}\n\nVisibility: ${review.meta.privacy}\nMade for kids: ${review.meta.made_for_kids ? 'Yes' : 'No'}`
      : `${review.meta.caption}\n\nPublishes a Reel to your feed immediately. The selected clip is staged in your bucket with an expiring fetch link, then removed after publication.`;
    const state = document.createElement('p'); state.className = 'help'; state.textContent = `Saved state: ${target.status}${target.status === 'uploaded' || target.status === 'published' ? ' · already uploaded; only pending cleanup will run' : ''}`;
    section.append(heading, text, state);
    return section;
}
$('close-review').addEventListener('click', () => $('upload-review').close());
$('upload-review').addEventListener('close', () => { $('upload-review').querySelectorAll('video').forEach(video => video.pause()); reviewId = ''; });
$('upload-now').addEventListener('click', async () => {
  if (!reviewId) return;
  try { await publishAction('commit', {review_id: reviewId}); $('upload-review').close(); $('upload-history').scrollIntoView({behavior: 'smooth'}); }
  catch (error) { showError('review-error', error.message); }
});
const formatSize = bytes => bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(2)} GB` : `${(bytes / 1024 ** 2).toFixed(1)} MB`;
$('saved-replay').addEventListener('change', event => {
  const id = event.target.value;
  if (!id) return;
  $('replay-url').value = `https://www.youtube.com/watch?v=${id}`;
  const prior = runs.find(run => run.source_id === id);
  if (prior) {
    $('game').value = prior.game;
    updateGameHelp();
  }
});
$('replay-url').addEventListener('input', () => { $('saved-replay').value = ''; });
function renderDownloads(downloads) {
  const key = JSON.stringify([downloads, busy, submitting]);
  if (key === downloadKey) return;
  downloadKey = key;
  const picker = $('saved-replay');
  const picked = picker.value;
  const ids = [...new Set(downloads.map(item => item.source_id))].reverse();
  picker.replaceChildren(new Option('Choose a downloaded stream…', ''));
  for (const id of ids) {
    const run = runs.find(item => item.source_id === id);
    const title = downloads.find(item => item.source_id === id && item.title)?.title;
    picker.add(new Option(title ? `${title} · ${id}` : run ? `${run.game === 'gta6' ? 'GTA 6' : 'Fortnite'} · ${id}` : id, id));
  }
  picker.value = ids.includes(picked) ? picked : '';
  picker.disabled = !ids.length || busy || submitting;
  $('download-total').textContent = downloads.length
    ? `${downloads.length} saved replays · ${formatSize(downloads.reduce((sum, item) => sum + item.bytes, 0))} · oldest first`
    : 'No saved stream downloads.';
  $('download-list').replaceChildren();
  for (const item of downloads) {
    const row = document.createElement('div'); row.className = 'upload-row';
    const label = document.createElement('span');
    label.textContent = `${item.name} · ${formatSize(item.bytes)} · ${new Date(item.modified * 1000).toLocaleDateString()}`;
    const button = document.createElement('button'); button.textContent = 'Remove download';
    button.disabled = busy || submitting;
    button.addEventListener('click', async () => {
      if (busy || submitting || !confirm(`Permanently remove ${item.name} (${formatSize(item.bytes)})? Clipper will download the stream again if you use its URL.`)) return;
      submitting = button.disabled = true;
      showError('download-error', '');
      try { await request('/api/downloads/remove', {name: item.name, modified: item.modified}); }
      catch (error) { showError('download-error', error.message); }
      finally { submitting = false; downloadKey = ''; await refresh(); }
    });
    row.append(label, button); $('download-list').append(row);
  }
}
// Poll only after the previous request finishes; leave video elements intact while playing.
async function poll() { await refresh(); setTimeout(poll, 2000); }
poll();
