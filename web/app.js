'use strict';
const $ = id => document.getElementById(id);
let token = '', runs = [], selected = '', rendered = '', lastResult = '', busy = false, submitting = false;
let publishClip = null, publishing = null, historyKey = '', reviewId = '';
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
    card.querySelector('.publish-clip').addEventListener('click', () => selectPublishClip(run, clip));
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
    const stage = [...log].reverse().find(line => /^(validate:|download:|analyze:|combat:|select:|transcribe:|render:|upload:)/.test(line));
    const result = runs.find(run => run.id === state.job.result_run);
    const stageLabel = state.job.kind === 'publish' ? (stage || 'Starting reviewed upload…')
      : !stage ? (state.job.kind === 'headline' ? 'Updating the clip headline…' : 'Starting replay processing…')
      : stage.startsWith('validate:') ? 'Checking the replay…'
      : stage.startsWith('download:') ? 'Downloading or reusing the replay…'
      : /^(analyze:|combat:)/.test(stage) ? 'Finding confirmed elimination moments…'
      : stage.startsWith('select:') ? 'Choosing distinct clips…'
      : stage.startsWith('transcribe:') ? 'Preparing speech captions…' : 'Rendering clips…';
    $('job-message').textContent = busy ? stageLabel
      : state.job.status === 'failed' ? (state.job.kind === 'publish' ? 'An upload needs attention. Check each destination in upload history.' : 'Processing stopped. Expand recent progress for the error, then retry.')
      : state.job.status === 'complete' ? (state.job.kind === 'publish' ? 'Upload finished. Open the saved links in upload history.' : state.job.kind === 'headline' ? 'Headline updated. Preview or download the refreshed clip.' : `${result?.clips.length || 0} clips ready. ${result?.clips.length ? 'Review them below.' : 'No moments met the selection requirements.'}`)
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
    publishing = state.publishing;
    renderPublishing();
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
function selectPublishClip(run, clip) {
  publishClip = {run: run.id, name: clip.name, revision: run.revision};
  $('publish-empty').hidden = true;
  $('publish-form').hidden = false;
  $('publish-preview').src = `${clip.url}?v=${run.revision}#t=0.1`;
  $('publish-selection').textContent = `${clip.name} · ${run.source_id} · ${time(clip.start)}–${time(clip.end)}`;
  $('post-title').value = clip.title || '';
  $('post-description').value = clip.description || '';
  $('post-caption').value = clip.description || clip.title || '';
  $('post-audience').value = '';
  showError('publish-error', '');
  $('publishing').scrollIntoView({behavior: 'smooth'});
  $('post-title').focus({preventScroll: true});
}
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
  const key = JSON.stringify([publishing.history, disabled]);
  if (key === historyKey) return;
  historyKey = key;
  $('upload-history').replaceChildren();
  if (!publishing.history.length) {
    const empty = document.createElement('p'); empty.className = 'help'; empty.textContent = 'No uploads yet.';
    $('upload-history').append(empty);
  }
  for (const item of publishing.history) {
    const row = document.createElement('div'); row.className = 'upload-row';
    const details = document.createElement('div');
    const title = document.createElement('h3'); title.textContent = `${item.target === 'youtube' ? 'YouTube' : 'Instagram'} · @${item.handle} · ${item.name}`;
    const status = document.createElement('p'); status.className = 'help';
    status.textContent = `${item.status} · ${item.progress}%${item.visibility ? ` · ${item.visibility}` : ''}${item.cleanup_pending ? ' · temporary storage copy remains' : ''}`;
    details.append(title, status);
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
    row.append(details, actions); $('upload-history').append(row);
  }
}
function postingFields() {
  $('youtube-fields').hidden = !$('post-youtube').checked;
  $('instagram-fields').hidden = !$('post-instagram').checked;
}
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
    openReview(await publishAction('prepare', {run: publishClip.run, clip: publishClip.name,
      youtube: $('post-youtube').checked, instagram: $('post-instagram').checked,
      title: $('post-title').value, description: $('post-description').value, caption: $('post-caption').value,
      privacy: $('post-privacy').value, made_for_kids: $('post-audience').value === 'yes'}));
  } catch (error) { showError('publish-error', error.message); }
});
function openReview(review) {
  reviewId = review.review_id;
  $('review-clip').textContent = `${review.name} · ${Math.round(review.duration)} sec · version ${review.sha}`;
  $('review-preview').src = review.preview + '#t=0.1';
  $('review-details').replaceChildren();
  for (const target of review.destinations) {
    const section = document.createElement('section');
    const heading = document.createElement('h3'); heading.textContent = `${target.target === 'youtube' ? 'YouTube' : 'Instagram'} · @${target.handle}`;
    const text = document.createElement('p');
    text.textContent = target.target === 'youtube'
      ? `${review.meta.title}\n\n${review.meta.description}\n\nVisibility: ${review.meta.privacy}\nMade for kids: ${review.meta.made_for_kids ? 'Yes' : 'No'}`
      : `${review.meta.caption}\n\nPublishes a Reel to your feed immediately. The selected clip is staged in your bucket with an expiring fetch link, then removed after publication.`;
    const state = document.createElement('p'); state.className = 'help'; state.textContent = `Saved state: ${target.status}${target.status === 'uploaded' || target.status === 'published' ? ' · already uploaded; only pending cleanup will run' : ''}`;
    section.append(heading, text, state); $('review-details').append(section);
  }
  showError('review-error', '');
  $('upload-now').textContent = review.retry ? 'Resume saved action' : 'Upload now';
  $('upload-review').showModal();
}
$('close-review').addEventListener('click', () => $('upload-review').close());
$('upload-review').addEventListener('close', () => { $('review-preview').pause(); reviewId = ''; });
$('upload-now').addEventListener('click', async () => {
  if (!reviewId) return;
  try { await publishAction('commit', {review_id: reviewId}); $('upload-review').close(); }
  catch (error) { showError('review-error', error.message); }
});
// Poll only after the previous request finishes; leave video elements intact while playing.
async function poll() { await refresh(); setTimeout(poll, 2000); }
poll();
