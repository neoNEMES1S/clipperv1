# Clipper Local Studio

A small local browser utility for a Fortnite streamer who wants combat Shorts without terminal commands. It wraps an existing Python pipeline on the same computer. The publishing extension connects only the user's chosen YouTube and Instagram accounts; extraction stays local. No billing, navigation sidebar, analytics, or marketing content.

## Workflow

One responsive page. A compact header names Clipper and shows Local workspace. The top processing panel accepts a completed YouTube replay URL and a maximum clip count (default 25). Combat-only selection is the default, stated in plain language: confirmed eliminations. A Generate clips button starts one job at a time. Show honest stage text and recent progress lines while running; never invent a percentage or completion estimate. Errors stay visible with retry guidance. Closing the browser does not stop processing.

Below: previous runs selector, source interval, number of finished clips, and Open output folder. Show existing results immediately. Three portrait video preview cards per desktop row, each with native playback controls, source timestamp, Download MP4 link, and any caption warning. This replay's actual existing results: three 36-second drafts, 7:02–7:38, 1:04:18–1:04:54, 3:41:00–3:41:36. One discreet sentence says drafts need review. Do not show fabricated thumbnails or statistics. Use dark video placeholders in a design draft; actual local videos will populate implementation.

## Visual system

Adapt the Neural Noir Interface Style library prompt to a compact utility. Keep the charcoal and warm gold palette, fine borders and restrained spacing; omit decorative neural lines, glows, glass blur and landing-page sections.

- Background #0a0a0a; panel #141414; input #1c1c1c; border #303030.
- Text #f5f3ef; secondary #b4b0a8; gold accent #c9b8a0; hover #e8d5b7; error #fca5a5.
- Native system sans-serif for all text; no downloaded fonts. Heading 30px/36px, section 19px/26px, body 14px/21px, labels 12px/18px. No serif typography in this utility adaptation.
- Max width 1160px, desktop gutter 32px, mobile 18px. Spacing 4/8/12/16/24/32/48px. Card radius 12px, controls 8px, border 1px. No shadows required.
- Solid gold primary button with charcoal text; neutral bordered secondary buttons. Clear keyboard focus, labels, minimum 44px action height, reduced-motion support. No ornamental assets or logo mark exists; use the product name as a heading.
- On phones, stack form fields and video cards; no horizontal scrolling. Native video aspect ratio 9:16 with a maximum visible height around 400px on desktop so results are usable without a huge scroll.
- Only brief color transitions, no looping decorative motion.

## Implementation constraints

Python standard-library localhost server with a static HTML/CSS/JS page, existing virtualenv and subprocess pipeline. No React, Node build, remote UI assets or hosted frontend. Mac and Windows double-click launchers. Existing CLI behavior and old results remain intact. Publishing may use official OAuth/storage SDKs and an OS credential store. Only a reviewed clip is transferred to selected platforms, with temporary signed storage for Instagram Login; no automatic publishing after extraction. See publishing-brief.md for the new flow.
