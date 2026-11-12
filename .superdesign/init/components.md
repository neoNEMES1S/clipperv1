# Components

Native HTML controls; no framework or UI package. The reusable clip-card template is cloned by web/app.js. Its source is below. Inputs/buttons/selects use the common stylesheet in theme.md.

```html
  <template id="clip-template">
    <article class="clip-card">
      <div class="video-frame"><video controls preload="metadata" playsinline></video></div>
      <div class="clip-info"><div class="clip-title"><h3></h3><span class="duration"></span></div><p class="interval"></p><p class="caption-note"></p>
        <form class="headline-form"><label>Top headline<input class="headline-input" type="text" maxlength="72" autocomplete="off"></label><p class="help">Leave blank to remove. The original clip is backed up.</p><button class="headline-button" type="submit">Save &amp; re-render</button><p class="headline-error error-text" role="alert" hidden></p></form>
        <a class="download" download>Download MP4 <span aria-hidden="true">↓</span></a></div>
    </article>
  </template>
```
