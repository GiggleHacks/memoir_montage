/* compilation_maker — front-end glue (iteration 2).
 * Rich per-file log rows, NSFW banner, footer telemetry, folder hashing.
 */

(function () {
    const $ = (id) => document.getElementById(id);

    const state = {
        folder: null,
        phase: "idle",
        eventCount: 0,
        pool: { indexed: 0, durations: [], longest: 0, total: 0 },
        constraints: null,  // last compile_constraints() result
    };
    const LOG_MAX = 500;
    const GRID_OPTIONS = [3, 4, 5, 6, 7, 8, 9, 10];

    /* file-extension → CSS path class. Per spec. */
    const EXT_CLASS = {
        // image
        jpg: "path-image", jpeg: "path-image", png: "path-image", webp: "path-image",
        gif: "path-image", bmp: "path-image", tiff: "path-image", tif: "path-image",
        // video
        mp4: "path-video", mov: "path-video", mkv: "path-video", webm: "path-video",
        avi: "path-video", m4v: "path-video", wmv: "path-video", flv: "path-video",
        mpg: "path-video", mpeg: "path-video",
        // pdf
        pdf: "path-pdf",
        // peak/waveform
        sfk: "path-peak", pkf: "path-peak", pek: "path-peak", cfa: "path-peak",
        // audio
        mp3: "path-audio", wav: "path-audio", flac: "path-audio", aac: "path-audio",
        ogg: "path-audio", m4a: "path-audio", wma: "path-audio", opus: "path-audio",
        // junk
        tmp: "path-junk", temp: "path-junk", bak: "path-junk",
        old: "path-junk", cache: "path-junk", log: "path-junk",
    };
    /* Match a filename token with a known extension (path or bare). */
    const PATH_RE = /([^\s"'`<>|,;]+?\.([A-Za-z0-9]{1,8}))(?=$|[\s"'`<>|,;])/g;

    function escapeHTML(s) {
        return String(s)
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
    function colorizePaths(message) {
        let html = escapeHTML(message);
        html = html.replace(PATH_RE, function (full, path, ext) {
            const cls = EXT_CLASS[ext.toLowerCase()];
            if (!cls) return full;
            return '<span class="' + cls + '">' + path + '</span>';
        });
        return html;
    }

    /* ---------- helpers ---------- */
    function nowTs() {
        return new Date().toTimeString().slice(0, 8);
    }

    /* deterministic-ish hash → hue 0..359 */
    function hashHue(str) {
        let h = 0;
        for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0;
        return Math.abs(h) % 360;
    }
    function folderColor(folder) {
        const hue = hashHue(folder || "");
        // pastel-ish pill: high lightness, mid sat
        return "hsl(" + hue + ", 62%, 68%)";
    }

    function sizeBucket(bytes) {
        const mb = (bytes || 0) / (1024 * 1024);
        if (mb < 50)   return { cls: "s-tiny",  label: mb.toFixed(1) + " MB" };
        if (mb < 500)  return { cls: "s-small", label: mb.toFixed(0) + " MB" };
        if (mb < 2000) return { cls: "s-med",   label: mb.toFixed(0) + " MB" };
        return            { cls: "s-big",   label: (mb / 1024).toFixed(2) + " GB" };
    }

    function trimToLog() {
        const log = $("log");
        while (log && log.childElementCount > LOG_MAX) log.removeChild(log.firstChild);
        if (log) log.scrollTop = log.scrollHeight;
    }

    /* ---------- log: plain line ---------- */
    function logLine(msg, level) {
        level = level || "info";
        const log = $("log"); if (!log) return;
        const div = document.createElement("div");
        div.className = "line " + level;
        div.innerHTML =
            '<span class="ts">[' + nowTs() + ']</span>' +
            '<span class="msg">' + colorizePaths(msg) + '</span>';
        log.appendChild(div);
        bumpCounter();
        trimToLog();
    }

    function bumpCounter() {
        state.eventCount += 1;
        const c = $("log-counter");
        if (c) c.textContent = state.eventCount + (state.eventCount === 1 ? " event" : " events");
    }

    /* ---------- log: rich file row ---------- */
    function logFileRow(result) {
        const log = $("log"); if (!log) return;

        if (result.nsfw_flagged) {
            const banner = document.createElement("div");
            banner.className = "nsfw-banner";
            banner.title = result.path || "";
            banner.innerHTML =
                '<span class="icon">🔞</span>' +
                '<span class="label">NSFW — WILL BE EXCLUDED</span>' +
                '<span class="name"></span>';
            banner.querySelector(".name").textContent = result.name || "";
            log.appendChild(banner);
        }

        const row = document.createElement("div");
        row.className = "row-file";
        row.title = result.path || "";

        const folder = document.createElement("span");
        folder.className = "folder-pill";
        folder.textContent = result.folder || "—";
        folder.style.background = folderColor(result.folder);

        const name = document.createElement("span");
        name.className = "file-name";
        name.textContent = result.name || "";

        const size = sizeBucket(result.size_bytes);
        const sizeEl = document.createElement("span");
        sizeEl.className = "size-badge " + size.cls;
        sizeEl.textContent = size.label;
        if (result.duration != null) {
            sizeEl.title = result.duration.toFixed(1) + " s";
        }

        const chips = document.createElement("span");
        chips.className = "chips";
        const passes = result.passes || {};
        const res = (result.width && result.height) ? result.width + "×" + result.height : "?";
        const srcReason = result.source_reason;
        const srcLabel = srcReason ? ("⚠ " + srcReason.toUpperCase()) : "SRC OK";
        const chipDefs = [
            { key: "nsfw",        label: "NSFW",   cls: "nsfw",   hover: result.nsfw_flagged ? "🔞 NSFW detected" : "Content OK" },
            { key: "orientation", label: result.is_vertical ? "📱VERT" : "HORZ", cls: result.is_vertical ? "vert" : "horz",
              hover: result.is_vertical ? "Vertical " + res + " — excluded" : "Horizontal " + res },
            { key: "resolution",  label: res,      cls: "res",    hover: result.is_lowres ? "⚠ Low-res — excluded" : "Resolution OK" },
            { key: "source",      label: srcLabel,  cls: "src",   hover: srcReason ? ("Flagged: " + srcReason + " — may be skipped") : "Filename looks like camera footage" },
            { key: "talk",        label: "TALK",   cls: "talk",   hover: "Speech: " + ((result.speech_fraction || 0) * 100).toFixed(0) + "%" },
        ];
        for (const d of chipDefs) {
            const chip = document.createElement("span");
            const pass = passes[d.key === "talk" ? "talking" : d.key];
            chip.className = "chip " + d.cls + (pass ? " ok" : " bad");
            chip.textContent = d.label;
            chip.title = d.hover + (pass ? "" : " (filter would skip)");
            chips.appendChild(chip);
        }

        row.appendChild(folder);
        row.appendChild(name);
        row.appendChild(sizeEl);
        row.appendChild(chips);
        log.appendChild(row);
        bumpCounter();
        trimToLog();
    }

    /* ---------- log: end-of-scan summary card ---------- */
    function formatDuration(seconds) {
        seconds = Math.max(0, Math.round(seconds || 0));
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = seconds % 60;
        if (h) return h + "h " + String(m).padStart(2, "0") + "m " + String(s).padStart(2, "0") + "s";
        if (m) return m + "m " + String(s).padStart(2, "0") + "s";
        return s + "s";
    }
    function formatBytes(bytes) {
        bytes = bytes || 0;
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
        if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + " MB";
        if (bytes < 1024 * 1024 * 1024 * 1024) return (bytes / (1024 * 1024 * 1024)).toFixed(2) + " GB";
        return (bytes / (1024 * 1024 * 1024 * 1024)).toFixed(2) + " TB";
    }
    function logCompileCard(summary) {
        const log = $("log"); if (!log) return;
        const card = document.createElement("div");
        card.className = "scan-summary";
        const out = summary.output || "—";
        const fileName = out.split(/[\\/]/).pop();
        const rows = [
            { label: "grid",        value: summary.grid + " x " + summary.grid, cls: "v-blue" },
            { label: "segments",    value: String(summary.segments || 0),       cls: "" },
            { label: "swap",        value: (summary.swap_seconds || 0) + " s",  cls: "" },
            { label: "length",      value: formatDuration(summary.total_seconds), cls: "v-talk" },
            { label: "render time", value: formatDuration(summary.seconds),     cls: "v-motion" },
        ];
        let inner =
            '<div class="ss-h">' +
                '<span class="ss-h-l">COMPILE COMPLETE</span>' +
                '<span class="ss-h-t">' + formatDuration(summary.seconds) + ' total</span>' +
            '</div>' +
            '<div class="ss-eligible">' +
                '<span class="ss-eligible-n" style="color: var(--accent-blue)">⇪</span>' +
                '<span class="ss-eligible-l">' + fileName + '</span>' +
            '</div>' +
            '<div class="ss-grid">';
        for (const r of rows) {
            inner += '<div class="ss-cell"><div class="ss-cell-l">' + r.label + '</div>' +
                     '<div class="ss-cell-v ' + r.cls + '"></div></div>';
        }
        inner += '</div>';
        card.innerHTML = inner;
        const cells = card.querySelectorAll(".ss-cell-v");
        rows.forEach((r, i) => { if (cells[i]) cells[i].textContent = r.value; });
        log.appendChild(card);
        bumpCounter();
        trimToLog();
    }

    function logSummaryCard(summary) {
        if (summary && summary.type === "compile") {
            logCompileCard(summary);
            return;
        }
        const log = $("log"); if (!log) return;
        const stats = summary.stats || {};
        const total = stats.total != null ? stats.total : (summary.scanned || 0);
        const card = document.createElement("div");
        card.className = "scan-summary";
        const stoppedEarly = !!summary.stopped_early;

        const rows = [
            { label: "videos found",   value: String(total),                                cls: "" },
            { label: "indexed now",    value: String(summary.indexed || 0),                  cls: "" },
            { label: "cached / reused",value: String(summary.cached || 0),                   cls: "" },
            { label: "failed",         value: String(summary.failed || 0),
              cls: (summary.failed || 0) > 0 ? "v-bad" : "" },
            { label: "total duration", value: formatDuration(stats.total_duration_seconds), cls: "v-blue" },
            { label: "total size",     value: formatBytes(stats.total_size_bytes),          cls: "v-blue" },
            { label: "NSFW detected",  value: String(stats.nsfw || 0),
              cls: (stats.nsfw || 0) > 0 ? "v-nsfw" : "" },
            { label: "with talking",   value: String(stats.talking || 0), cls: "v-talk" },
        ];

        const headerLabel = stoppedEarly ? "STOPPED — PARTIAL INDEX" : "SCAN COMPLETE";
        let inner =
            '<div class="ss-h">' +
                '<span class="ss-h-l">' + headerLabel + '</span>' +
                '<span class="ss-h-t">' + formatDuration(summary.seconds) + ' run time</span>' +
            '</div>' +
            '<div class="ss-eligible">' +
                '<span class="ss-eligible-n">' + (stats.eligible != null ? stats.eligible : 0) + '</span>' +
                '<span class="ss-eligible-l">videos pass all active filters</span>' +
            '</div>' +
            '<div class="ss-grid">';
        for (const r of rows) {
            inner +=
                '<div class="ss-cell">' +
                    '<div class="ss-cell-l">' + r.label + '</div>' +
                    '<div class="ss-cell-v ' + r.cls + '"></div>' +
                '</div>';
        }
        inner += '</div>';
        card.innerHTML = inner;

        const cells = card.querySelectorAll(".ss-cell-v");
        rows.forEach((r, i) => { if (cells[i]) cells[i].textContent = r.value; });

        log.appendChild(card);
        bumpCounter();
        trimToLog();
    }

    /* ---------- telemetry mini-bars (8 cells) ---------- */
    function ensureSeg(id, count) {
        const root = $(id);
        if (!root) return;
        if (root.childElementCount === count) return;
        root.innerHTML = "";
        for (let i = 0; i < count; i++) {
            const c = document.createElement("div");
            c.className = "cell";
            root.appendChild(c);
        }
    }
    function updateSeg(id, pct, label) {
        ensureSeg(id, 8);
        const root = $(id); if (!root) return;
        const cells = root.children;
        const safe = Math.max(0, Math.min(100, pct || 0));
        const lit  = Math.round((safe / 100) * cells.length);
        for (let i = 0; i < cells.length; i++) {
            const c = cells[i];
            c.className = "cell";
            if (i < lit) {
                c.classList.add("on");
                if (i >= 7) c.classList.add("err");
                else if (i >= 6) c.classList.add("warn");
            }
        }
        const v = $(id + "-v");
        if (v) v.textContent = label != null ? label : Math.round(safe) + "%";
    }

    function setIndeterminateProgress(on) {
        const bar = $("bar"); if (!bar) return;
        bar.classList.toggle("indeterminate", !!on);
        if (on) {
            $("bar-fill").style.width = "100%";
            $("bar-pct").textContent = "…";
        }
    }

    function renderIndexStats(agg) {
        const box = $("index-stats"); if (!box) return;
        if (!agg || !agg.total) {
            box.hidden = true;
            return;
        }
        box.hidden = false;
        const eligDur = agg.eligible_duration_seconds || 0;
        const totDur  = agg.total_duration_seconds || 0;
        const runtimeEl = $("is-runtime");
        if (runtimeEl) {
            runtimeEl.textContent = formatDuration(eligDur);
            runtimeEl.title = "Eligible runtime: " + formatDuration(eligDur)
                            + "  ·  total indexed runtime: " + formatDuration(totDur);
        }
        const indexedEl = $("is-indexed");
        if (indexedEl) {
            indexedEl.textContent = agg.total + (agg.failed ? "  (" + agg.failed + " failed)" : "");
        }
        const chips = $("is-chips");
        if (chips) {
            chips.innerHTML = "";
            const defs = [
                { k: "talking", l: "talk",   cls: "v-talk" },
                { k: "motion",  l: "motion", cls: "v-motion" },
                { k: "face",    l: "face",   cls: "v-face" },
                { k: "nsfw",    l: "nsfw",   cls: "v-nsfw" },
            ];
            for (const d of defs) {
                const n = agg[d.k] || 0;
                const s = document.createElement("span");
                s.className = "is-chip " + d.cls;
                s.textContent = d.l + " " + n;
                chips.appendChild(s);
            }
        }
    }

    /* ---------- phase / log header state ---------- */
    function setPhase(p) {
        state.phase = p;

        const led = $("rec");
        const status = $("log-status");
        let statusText = "IDLE", statusCls = "idle", ledCls = "led";
        if (p === "indexing") {
            statusText = "● INDEX"; statusCls = "rec"; ledCls = "led rec";
        } else if (p === "compiling") {
            statusText = "● RENDER"; statusCls = "rec"; ledCls = "led rec";
        } else if (p === "concat") {
            statusText = "⟳ CONCAT"; statusCls = "concat"; ledCls = "led concat";
        } else if (p === "paused") {
            statusText = "PAUSED"; statusCls = "paused"; ledCls = "led paused";
        }
        if (led)    led.className = ledCls;
        if (status) { status.textContent = statusText; status.className = "log-status " + statusCls; }

        const cancelBtn = $("btn-cancel");
        if (cancelBtn) cancelBtn.disabled = (p === "idle");
        const indexBtn = $("btn-index");
        const compileBtn = $("btn-compile");
        if (indexBtn) indexBtn.disabled = (p !== "idle");
        if (compileBtn) compileBtn.disabled = (p !== "idle");
    }

    /* ---------- event dispatch ---------- */
    function onEvent(ev) {
        const tag = ev[0];
        if (tag === "log")     { logLine(ev[1], ev[2]); return; }
        if (tag === "current") {
            $("cur-path").textContent = ev[1] || "—";
            $("cur-sub").textContent  = ev[2] || "";
            return;
        }
        if (tag === "counts") {
            setIndeterminateProgress(false);
            const done = ev[1], total = ev[2], rate = ev[3], eta = ev[4];
            const pct = total > 0 ? (done / total) * 100 : 0;
            $("bar-fill").style.width = pct + "%";
            $("bar-pct").textContent = Math.round(pct) + " %";
            $("p-counts").textContent = done + " / " + total;
            $("p-rate").textContent = (rate || 0).toFixed(1) + " /s";
            $("p-eta").textContent = "eta " + (eta || "--:--");
            return;
        }
        if (tag === "stats") {
            const cpu = ev[1], ram = ev[2], gpu = ev[3], vram = ev[4];
            updateSeg("stat-cpu", cpu);
            updateSeg("stat-ram", ram);
            if (gpu != null) { $("stat-gpu-box").style.display = ""; updateSeg("stat-gpu", gpu); }
            else             { $("stat-gpu-box").style.display = "none"; }
            if (vram != null){ $("stat-vram-box").style.display = ""; updateSeg("stat-vram", vram); }
            else             { $("stat-vram-box").style.display = "none"; }
            return;
        }
        if (tag === "phase") { setPhase(ev[1]); return; }
        if (tag === "phase_label") {
            const el = $("phase-label");
            if (el) el.textContent = ev[1] || "";
            return;
        }
        if (tag === "enumerate") {
            const found = ev[1] || 0;
            const dir   = ev[2] || "";
            setIndeterminateProgress(true);
            $("p-counts").textContent = "found " + found;
            $("p-rate").textContent   = "";
            $("p-eta").textContent    = "";
            $("cur-path").textContent = dir || "scanning…";
            $("cur-sub").textContent  = "enumerating";
            const pl = $("phase-label");
            if (pl) pl.textContent = "Enumerating · " + found + " found";
            return;
        }
        if (tag === "eligible") {
            $("eligible-n").textContent = String(ev[1]);
            return;
        }
        if (tag === "stats_index") {
            renderIndexStats(ev[1] || {});
            return;
        }
        if (tag === "analysis") {
            logFileRow(ev[2] || {});
            return;
        }
        if (tag === "done") {
            logSummaryCard(ev[1] || {});
            // Index just finished — refresh pool stats so the helper updates.
            refreshPool();
            return;
        }
    }

    /* ---------- filter detail chips ---------- */
    const FILTER_PRESETS = {
        strict: {
            talking_required: true, source_allowlist_strict: true,
            exclude_vertical: true, exclude_downloads: true, exclude_low_resolution: true,
        },
        normal: {
            talking_required: false, source_allowlist_strict: false,
            exclude_vertical: true, exclude_downloads: true, exclude_low_resolution: true,
        },
        off: {
            talking_required: false, source_allowlist_strict: false,
            exclude_vertical: false, exclude_downloads: false, exclude_low_resolution: false,
        },
        custom: {
            talking_required: false, source_allowlist_strict: false,
            exclude_vertical: true, exclude_downloads: true, exclude_low_resolution: true,
        },
    };
    const CUSTOM_LS_KEY = "mm.custom_filters";
    const FILTER_LABELS = {
        talking_required: "TALK", source_allowlist_strict: "CAMERA ONLY",
        exclude_vertical: "NO VERT", exclude_downloads: "NO DOWNLOADS", exclude_low_resolution: "720p+",
    };
    const AUDIO_DESCS = {
        all:  "Play audio from all clips simultaneously.",
        mute: "No audio — output will be completely silent.",
        solo: "One clip at a time — cycles through the grid with a gold highlight.",
    };
    function loadCustomFlags() {
        try {
            const raw = localStorage.getItem(CUSTOM_LS_KEY);
            if (raw) return JSON.parse(raw);
        } catch (e) {}
        return Object.assign({}, FILTER_PRESETS.custom, { min_duration: 5.5 });
    }
    function saveCustomFlags(flags) {
        try { localStorage.setItem(CUSTOM_LS_KEY, JSON.stringify(flags)); } catch (e) {}
    }
    function applyFlagsToUI(flags) {
        if ($("cf-talking")) $("cf-talking").checked = !!flags.talking_required;
        if ($("cf-camera"))  $("cf-camera").checked  = !!flags.source_allowlist_strict;
        if ($("cf-novert"))  $("cf-novert").checked  = !!flags.exclude_vertical;
        if ($("cf-nodl"))    $("cf-nodl").checked    = !!flags.exclude_downloads;
        if ($("cf-nolow"))   $("cf-nolow").checked   = !!flags.exclude_low_resolution;
        if ($("cf-mindur")) {
            const v = flags.min_duration != null ? flags.min_duration : 5.5;
            $("cf-mindur").value = String(v);
            syncMinDurLabel();
        }
    }
    function gatherCustomFlags() {
        return {
            talking_required:        !!($("cf-talking") && $("cf-talking").checked),
            source_allowlist_strict: !!($("cf-camera")  && $("cf-camera").checked),
            exclude_vertical:        !!($("cf-novert")  && $("cf-novert").checked),
            exclude_downloads:       !!($("cf-nodl")    && $("cf-nodl").checked),
            exclude_low_resolution:  !!($("cf-nolow")   && $("cf-nolow").checked),
            min_duration:            parseFloat(($("cf-mindur") && $("cf-mindur").value) || "5.5"),
        };
    }
    function syncMinDurLabel() {
        const el = $("cf-mindur-val"); const inp = $("cf-mindur");
        if (el && inp) el.textContent = parseFloat(inp.value).toFixed(1) + " s";
    }

    function _setPreset(name) {
        document.querySelectorAll(".preset-btn").forEach(btn => {
            btn.classList.toggle("active", btn.dataset.preset === name);
        });
        // Checkboxes always reflect what the active preset enables. For Custom,
        // we pull the user's saved selections; for the named presets we mirror
        // the preset definition (with min_duration baked in).
        let flags;
        if (name === "custom") {
            flags = loadCustomFlags();
        } else {
            const p = FILTER_PRESETS[name] || FILTER_PRESETS.strict;
            flags = Object.assign({}, p, {
                min_duration: name === "off" ? 0 : 5.5,
            });
        }
        applyFlagsToUI(flags);
    }

    function _setNsfwMode(mode) {
        document.querySelectorAll(".nsfw-btn").forEach(btn => {
            btn.classList.toggle("active", btn.dataset.nsfw === mode);
        });
    }

    function _setAudioMode(mode) {
        document.querySelectorAll(".audio-btn").forEach(btn => {
            btn.classList.toggle("active", btn.dataset.mode === mode);
        });
        const desc = $("audio-mode-desc");
        if (desc) desc.textContent = AUDIO_DESCS[mode] || "";
    }

    function onSettings(s) {
        if (!s) return;
        if (s.last_folder) {
            state.folder = s.last_folder;
            $("folder-readout").value = s.last_folder;
            $("folderpath").textContent = s.last_folder;
        }
        const f = s.filters || {};
        _setPreset(f.preset || "strict");
        _setNsfwMode(f.nsfw_mode || "exclude");

        const o = s.output || {};
        if (o.grid)          $("o-grid").value  = String(o.grid);
        if (o.total_seconds) { $("o-total").value = o.total_seconds; syncSlider("o-total"); }
        if (o.swap_seconds)  { $("o-swap").value  = o.swap_seconds;  syncSlider("o-swap"); }
        if (typeof o.border         === "boolean") $("o-border").checked = o.border;
        if (typeof o.filename_label === "boolean") $("o-fname").checked  = o.filename_label;
        if (typeof o.year_label     === "boolean") $("o-year").checked   = o.year_label;
        if (o.audio_mode) _setAudioMode(o.audio_mode);
        if (typeof o.grid_ramp      === "boolean" && $("o-ramp")) $("o-ramp").checked = o.grid_ramp;
        if (typeof o.auto_open      === "boolean" && $("o-autoopen")) $("o-autoopen").checked = o.auto_open;
        if (o.order) _setOrder(o.order);
        else if (o.no_repeat) _setOrder("no_repeat");
        else _setOrder("chronological");
        updateRampPreview();
    }

    function syncSlider(id) {
        const el = $(id); if (!el) return;
        const val = parseInt(el.value, 10);
        const label = $(id + "-val");
        if (label) label.textContent = fmtSeconds(val);
    }

    window._cm = { onEvent, onSettings };

    /* ---------- wire ---------- */
    function gatherFilters() {
        const active = document.querySelector(".preset-btn.active");
        const nsfwActive = document.querySelector(".nsfw-btn.active");
        const preset = active ? active.dataset.preset : "strict";
        const out = {
            preset: preset,
            nsfw_mode: nsfwActive ? nsfwActive.dataset.nsfw : "exclude",
        };
        if (preset === "custom") Object.assign(out, gatherCustomFlags());
        return out;
    }
    function buildRampSequence(maxN, segments) {
        // 1, 1, 2, 2, 3, 3, 4, 4, ... up to maxN, then hold maxN
        const seq = [];
        let n = 1;
        let repeat = 0;
        for (let i = 0; i < segments; i++) {
            seq.push(n);
            repeat++;
            if (repeat >= 2 && n < maxN) {
                n++;
                repeat = 0;
            }
        }
        return seq;
    }

    function updateRampPreview() {
        const el = $("ramp-preview"); if (!el) return;
        const ramp = $("o-ramp");
        if (!ramp || !ramp.checked) { el.textContent = ""; return; }
        const maxN = parseInt($("o-grid").value, 10) || 3;
        const total = parseInt($("o-total").value, 10) || 120;
        const swap = parseInt($("o-swap").value, 10) || 5;
        const segs = Math.max(1, Math.floor(total / swap));
        const seq = buildRampSequence(maxN, segs);
        const labels = seq.map(n => n === 1 ? "1" : n + "×" + n);
        el.textContent = labels.join(" → ");
        el.title = seq.length + " segments: " + labels.join(" → ");
    }

    function gatherOutput() {
        const audioActive = document.querySelector(".audio-btn.active");
        const orderActive = document.querySelector(".order-btn.active");
        const order = orderActive ? orderActive.dataset.order : "chronological";
        return {
            grid:           parseInt($("o-grid").value, 10) || 3,
            total_seconds:  parseInt($("o-total").value, 10),
            swap_seconds:   parseInt($("o-swap").value, 10),
            border:         $("o-border").checked,
            filename_label: $("o-fname").checked,
            year_label:     $("o-year").checked,
            order:          order,
            no_repeat:      (order === "no_repeat"),
            audio_mode:     audioActive ? audioActive.dataset.mode : "all",
            grid_ramp:      ($("o-ramp") && $("o-ramp").checked) ? true : false,
            auto_open:      ($("o-autoopen") && $("o-autoopen").checked) ? true : false,
        };
    }

    const ORDER_DESCS = {
        chronological: "Oldest first — your memoir flows from past to present.",
        random:        "Random selection per segment.",
        no_repeat:     "Shuffled deck — no clip repeats until the pool is exhausted.",
    };
    function _setOrder(name) {
        document.querySelectorAll(".order-btn").forEach(btn => {
            btn.classList.toggle("active", btn.dataset.order === name);
        });
        const d = $("order-desc");
        if (d) d.textContent = ORDER_DESCS[name] || "";
    }

    function setStatusPill(status) {
        const pill = $("modal-status");
        if (!pill) return;
        pill.className = "status-pill " + status;
        const labels = { ready: "READY", limited: "LIMITED", impossible: "IMPOSSIBLE", checking: "CHECKING…" };
        pill.textContent = labels[status] || status.toUpperCase();
    }

    function rebuildGridOptions(constraints) {
        const sel = $("o-grid"); if (!sel) return;
        const current = sel.value;
        sel.innerHTML = "";
        const tooltips = (constraints && constraints.tooltips) || {};
        for (const n of GRID_OPTIONS) {
            const opt = document.createElement("option");
            opt.value = String(n);
            const cells = n * n;
            opt.textContent = n + " × " + n + " — " + cells + " cells";
            const reason = tooltips[String(n)];
            if (reason) {
                opt.disabled = true;
                opt.title = reason;
                opt.textContent += "  ✗";
            }
            sel.appendChild(opt);
        }
        // Restore selection if still valid, else snap to recommended
        const wantedOpt = sel.querySelector('option[value="' + current + '"]');
        if (wantedOpt && !wantedOpt.disabled) {
            sel.value = current;
        } else if (constraints && constraints.recommended && constraints.recommended.grid) {
            sel.value = String(constraints.recommended.grid);
        } else {
            const firstEnabled = Array.from(sel.options).find(o => !o.disabled);
            if (firstEnabled) sel.value = firstEnabled.value;
        }
    }

    function updateModalCoverage(validation) {
        const cov = $("modal-coverage"); if (!cov) return;
        if (!validation || validation.cells === 0) {
            cov.textContent = "";
            return;
        }
        const used = validation.used_seconds || 0;
        const avail = validation.available_seconds || 0;
        const ratio = avail > 0 ? (used / avail) : 0;
        const pct = Math.round(ratio * 100);
        cov.textContent =
            validation.cells + " cells × " + Math.round(used / Math.max(1, validation.cells)) +
            "s output = " + fmtSeconds(used) + " consumed of " + fmtSeconds(avail) +
            " pool (" + pct + "% coverage, ~" + ratio.toFixed(2) + "× per cell)";
        cov.className = "modal-coverage" + (ratio > 1.0 ? " over" : "");
    }

    function updateModalTotalHint(validation, constraints) {
        const hint = $("o-total-hint"); if (!hint) return;
        if (!validation) { hint.textContent = "How long the finished video will be."; return; }
        const max = validation.max_total_for_grid || 0;
        const input = $("o-total");
        // Apply dynamic max — but allow override (status will go to LIMITED)
        if (input) input.setAttribute("data-soft-max", String(max));
        if (max > 0) {
            hint.textContent =
                "Max without repetition at this grid: " + fmtSeconds(max) +
                " · pool: " + fmtSeconds(validation.available_seconds || 0);
        } else {
            hint.textContent = "How long the finished video will be.";
        }
    }

    function updateModalWarnings(validation) {
        const box = $("modal-warn"); if (!box) return;
        const msgs = [].concat(validation.reasons || []).concat(validation.warnings || []);
        if (msgs.length === 0) {
            box.hidden = true;
            box.textContent = "";
        } else {
            box.hidden = false;
            box.textContent = msgs.join("  ·  ");
            box.className = "modal-warn " + (validation.status === "impossible" ? "bad" : "warn");
        }
    }

    async function validateModal() {
        if (!state.folder) return;
        const out = gatherOutput();
        const segs  = Math.max(1, Math.floor(out.total_seconds / out.swap_seconds));
        const est = $("modal-est");
        if (est) {
            if (out.grid_ramp) {
                const seq = buildRampSequence(out.grid, segs);
                const totalCells = seq.reduce((s, n) => s + n * n, 0);
                est.textContent =
                    "GRID RAMP · " + segs + " segment" + (segs === 1 ? "" : "s") +
                    " · " + totalCells + " total cells · 1→" + out.grid + "×" + out.grid +
                    " · ~" + (segs * out.swap_seconds) + "s of final video";
            } else {
                const cells = out.grid * out.grid;
                est.textContent =
                    cells + " cells per segment · " + segs + " segment" + (segs === 1 ? "" : "s") +
                    " · ~" + (segs * out.swap_seconds) + "s of final video";
            }
        }
        try {
            const v = await window.pywebview.api.validate_compile_options(state.folder, out);
            setStatusPill(v.status || "impossible");
            updateModalCoverage(v);
            updateModalTotalHint(v, state.constraints);
            updateModalWarnings(v);
            const render = $("modal-render");
            if (render) render.disabled = (v.status === "impossible");
        } catch (e) {
            setStatusPill("impossible");
            const render = $("modal-render");
            if (render) render.disabled = true;
        }
        updateModalPoolReadout();
    }

    async function refreshConstraints(swap_seconds) {
        if (!state.folder) { state.constraints = null; return; }
        const audioActive = document.querySelector(".audio-btn.active");
        const audioMode = audioActive ? audioActive.dataset.mode : "all";
        try {
            state.constraints = await window.pywebview.api.compile_constraints(
                state.folder, swap_seconds || 5, audioMode,
            );
        } catch (e) {
            state.constraints = null;
        }
        rebuildGridOptions(state.constraints);
        updateTotalSliderRange();
    }

    // Back-compat shim — older callers used updateModalEstimate.
    function updateModalEstimate() { validateModal(); }

    function fmtSeconds(s) {
        s = Math.max(0, Math.round(s || 0));
        if (s < 60) return s + "s";
        const m = Math.floor(s / 60), r = s % 60;
        if (m < 60) return m + "m " + String(r).padStart(2, "0") + "s";
        const h = Math.floor(m / 60), rm = m % 60;
        return h + "h " + String(rm).padStart(2, "0") + "m";
    }

    function updateModalPoolReadout() {
        // Drive purely from the constraints fetch (matches what the compile pipeline uses).
        const el = $("modal-pool");
        if (!el) return;
        const c = state.constraints;
        if (!c) {
            el.textContent = "checking indexed pool…";
            el.classList.remove("bad");
            return;
        }
        if ((c.unique_clips || 0) === 0) {
            el.textContent = "⚠ this folder has not been indexed (or all clips are too short / muted). Close this and click INDEX.";
            el.classList.add("bad");
            return;
        }
        el.classList.remove("bad");
        el.textContent =
            "Available footage: " + fmtSeconds(c.available_seconds) +
            " · " + c.unique_clips + " usable clip" + (c.unique_clips === 1 ? "" : "s") +
            " · longest " + (c.longest_seconds || 0).toFixed(1) + "s" +
            " · shortest " + (c.shortest_seconds || 0).toFixed(1) + "s";
    }

    async function refreshPool() {
        if (!state.folder) {
            state.pool = { indexed: 0, durations: [], longest: 0, total: 0 };
            return;
        }
        try {
            const r = await window.pywebview.api.duration_breakdown(state.folder);
            state.pool = r || { indexed: 0, durations: [], longest: 0, total: 0 };
        } catch (e) {
            state.pool = { indexed: 0, durations: [], longest: 0, total: 0 };
        }
    }

    async function openCompileModal() {
        if (!state.folder) { logLine("select a folder first", "warn"); return; }
        $("modal-backdrop").hidden = false;
        setStatusPill("checking");
        const swap = parseInt($("o-swap").value, 10) || 5;
        await refreshConstraints(swap);
        await validateModal();
        setTimeout(() => $("modal-render").focus(), 80);
    }
    function closeCompileModal() {
        $("modal-backdrop").hidden = true;
    }

    function applyRecommended() {
        const c = state.constraints;
        if (!c || !c.recommended || !c.recommended.grid) {
            logLine("no recommendation available yet", "warn");
            return;
        }
        const r = c.recommended;
        $("o-grid").value  = String(r.grid);
        $("o-swap").value  = String(r.swap_seconds);
        $("o-total").value = String(Math.round(r.total_seconds));
        syncSlider("o-total");
        syncSlider("o-swap");
        validateModal();
    }

    function updateTotalSliderRange() {
        const slider = $("o-total"); if (!slider) return;
        const c = state.constraints;
        if (c && c.available_seconds > 0) {
            // Hard cap on total length: pool size (the "Bitcoin wallet" rule).
            const maxVal = Math.max(parseInt(slider.min, 10) || 5, Math.floor(c.available_seconds));
            slider.max = String(Math.min(maxVal, 3600));
            slider.disabled = false;
            if (parseInt(slider.value, 10) > parseInt(slider.max, 10)) {
                slider.value = slider.max;
                syncSlider("o-total");
            }
            const minEl = $("o-total-min");
            const maxEl = $("o-total-max");
            if (minEl) minEl.textContent = slider.min + "s";
            if (maxEl) maxEl.textContent = fmtSeconds(parseInt(slider.max, 10));
        } else if (c) {
            // No pool: disable
            slider.disabled = true;
            const maxEl = $("o-total-max");
            if (maxEl) maxEl.textContent = "0s — index videos first";
        }
        updateSwapSliderRange();
    }

    function updateSwapSliderRange() {
        const slider = $("o-swap"); if (!slider) return;
        const c = state.constraints;
        if (c && c.longest_seconds > 0) {
            // Swap can't exceed the longest eligible clip (with a small safety margin).
            const cap = Math.max(1, Math.floor(c.longest_seconds - 0.1));
            slider.max = String(Math.min(cap, 20));
            slider.disabled = false;
            if (parseInt(slider.value, 10) > parseInt(slider.max, 10)) {
                slider.value = slider.max;
                syncSlider("o-swap");
            }
            const range = slider.parentElement && slider.parentElement.querySelector(".slider-range");
            if (range) range.lastElementChild.textContent = slider.max + "s";
        }
    }

    function bind() {
        $("btn-folder").addEventListener("click", async () => {
            const f = await window.pywebview.api.select_folder();
            if (f) {
                state.folder = f;
                $("folder-readout").value = f;
                $("folderpath").textContent = f;
                await refreshPool();
            }
        });
        $("btn-index").addEventListener("click", async () => {
            if (!state.folder) { logLine("select a folder first", "warn"); return; }
            await window.pywebview.api.start_index(state.folder);
        });
        $("btn-compile").addEventListener("click", openCompileModal);
        $("btn-cancel").addEventListener("click", () => {
            window.pywebview.api.cancel();
        });
        document.querySelectorAll(".preset-btn").forEach(btn => {
            btn.addEventListener("click", async () => {
                _setPreset(btn.dataset.preset);
                await window.pywebview.api.save_filters(gatherFilters());
                await refreshConstraints(parseInt($("o-swap").value, 10) || 5);
            });
        });
        const filterInputs = ["cf-talking", "cf-camera", "cf-novert", "cf-nodl", "cf-nolow", "cf-mindur"];
        filterInputs.forEach(id => {
            const el = $(id); if (!el) return;
            const onTouch = async () => {
                // Any manual change flips the preset to Custom and remembers
                // the full snapshot of checkboxes/slider.
                const active = document.querySelector(".preset-btn.active");
                if (!active || active.dataset.preset !== "custom") {
                    document.querySelectorAll(".preset-btn").forEach(b => {
                        b.classList.toggle("active", b.dataset.preset === "custom");
                    });
                }
                saveCustomFlags(gatherCustomFlags());
                syncMinDurLabel();
                await window.pywebview.api.save_filters(gatherFilters());
                await refreshConstraints(parseInt($("o-swap").value, 10) || 5);
            };
            el.addEventListener("change", onTouch);
            if (id === "cf-mindur") el.addEventListener("input", syncMinDurLabel);
        });
        document.querySelectorAll(".order-btn").forEach(btn => {
            btn.addEventListener("click", async () => {
                _setOrder(btn.dataset.order);
                await window.pywebview.api.save_output_options(gatherOutput());
                validateModal();
            });
        });
        document.querySelectorAll(".nsfw-btn").forEach(btn => {
            btn.addEventListener("click", async () => {
                _setNsfwMode(btn.dataset.nsfw);
                await window.pywebview.api.save_filters(gatherFilters());
            });
        });

        // ----- compile modal -----
        $("modal-cancel").addEventListener("click", closeCompileModal);
        $("modal-close" ).addEventListener("click", closeCompileModal);
        $("modal-backdrop").addEventListener("click", (e) => {
            if (e.target === $("modal-backdrop")) closeCompileModal();
        });
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape" && !$("modal-backdrop").hidden) closeCompileModal();
        });
        ["o-grid","o-total","o-swap","o-border","o-fname","o-year","o-norepeat","o-ramp","o-autoopen"].forEach(id => {
            const el = $(id); if (!el) return;
            el.addEventListener("change", async () => {
                syncSlider(id);
                updateRampPreview();
                await window.pywebview.api.save_output_options(gatherOutput());
                if (id === "o-swap") {
                    await refreshConstraints(parseInt($("o-swap").value, 10) || 5);
                }
                validateModal();
            });
            el.addEventListener("input", () => {
                syncSlider(id);
                updateRampPreview();
                validateModal();
            });
        });
        document.querySelectorAll(".audio-btn").forEach(btn => {
            btn.addEventListener("click", async () => {
                _setAudioMode(btn.dataset.mode);
                await window.pywebview.api.save_output_options(gatherOutput());
                await refreshConstraints(parseInt($("o-swap").value, 10) || 5);
                validateModal();
            });
        });
        const recBtn = $("modal-recommend");
        if (recBtn) recBtn.addEventListener("click", applyRecommended);

        $("modal-render").addEventListener("click", async () => {
            const opts = gatherOutput();
            await window.pywebview.api.save_output_options(opts);
            closeCompileModal();
            await window.pywebview.api.start_compile(state.folder, opts);
        });
    }

    function pywebviewReady(cb) {
        let fired = false;
        const fire = () => { if (!fired) { fired = true; cb(); } };
        if (window.pywebview && window.pywebview.api) { fire(); return; }
        window.addEventListener("pywebviewready", fire, { once: true });
        let tries = 0;
        const id = setInterval(() => {
            if (fired) { clearInterval(id); return; }
            if (window.pywebview && window.pywebview.api) { clearInterval(id); fire(); }
            else if (++tries > 50) { clearInterval(id); logLine("bridge timeout: disconnected mode", "warn"); }
        }, 100);
    }

    document.addEventListener("DOMContentLoaded", () => {
        bind();
        logLine("ui loaded", "info");
        updateSeg("stat-cpu", 0);
        updateSeg("stat-ram", 0);
        pywebviewReady(async () => {
            logLine("bridge ready", "ok");
            try {
                const v = await window.pywebview.api.app_version();
                const el = $("app-ver");
                if (el && v) el.textContent = "v" + v;
            } catch (e) { /* leave placeholder */ }
            if (state.folder) refreshPool();
        });
    });
})();
