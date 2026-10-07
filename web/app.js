/* ---------------------------------------------------------------
   منطق رابط کاربری — تب‌بندی‌شده، تم روشن
   --------------------------------------------------------------- */

const state = {
  analysis: null,
  sheets: [],
  layers: [],
  tokens: [],
  layerMap: {},        // layer_id -> {mode, column, tokens:{}, direction}
  sheetSettings: {},   // sheet name -> {enabled, col1, col2, sep, prefix, suffix, from, to, folder, psd, templateColumn}
  pollTimer: null,
  activeTab: "files",
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

/* ------------------------------------------------------------ ابزارها */

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch (e) {
    throw new Error("پاسخ نامعتبر از سرور: " + text.slice(0, 160));
  }
}

const faNumber = (value) => String(value ?? "").replace(/[0-9]/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]);

function setStatus(message, type = "ok") {
  const box = $("#fileStatus");
  box.classList.remove("hidden", "ok", "warn", "error");
  box.classList.add(type);
  box.innerHTML = message;
}

function showErrors(boxSel, title, items) {
  const box = $(boxSel);
  if (!items || !items.length) {
    box.classList.add("hidden");
    box.innerHTML = "";
    return;
  }
  box.classList.remove("hidden");
  box.innerHTML = `<strong>${title}</strong><ul>${items.map((i) => `<li>${i}</li>`).join("")}</ul>`;
}

/* --------------------------------------------------------------- تب‌ها */

function setTabEnabled(name, enabled) {
  const tab = document.querySelector(`.tab[data-tab="${name}"]`);
  if (tab) tab.disabled = !enabled;
}

function showTab(name) {
  state.activeTab = name;
  $$(".tab").forEach((tab) => tab.classList.toggle("is-active", tab.dataset.tab === name));
  $$(".panel").forEach((panel) => panel.classList.toggle("is-active", panel.dataset.panel === name));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

$$(".tab").forEach((tab) => (tab.onclick = () => showTab(tab.dataset.tab)));
$$("[data-goto]").forEach((button) => {
  button.onclick = () => {
    const target = button.dataset.goto;
    const tab = document.querySelector(`.tab[data-tab="${target}"]`);
    if (tab && !tab.disabled) showTab(target);
  };
});

/* --------------------------------------------------------- فایل و پوشه */

function targetInput(kind) {
  if (kind === "excel") return $("#excelPath");
  if (kind === "psd") return $("#psdPath");
  if (kind === "dir") return $("#outDir");
  if (kind === "font") return $("#optFont");
  return null;
}

const PICK_TITLES = {
  excel: "فایل اکسل را انتخاب کنید",
  psd: "فایل فتوشاپ (PSD) را انتخاب کنید",
  dir: "پوشه‌ی مقصد را انتخاب کنید",
  font: "فایل فونت را انتخاب کنید (.ttf / .otf)",
};

async function pickPath(kind) {
  const exts = kind === "excel" ? ".xlsx,.xlsm" : kind === "psd" ? ".psd,.psb" : kind === "font" ? ".ttf,.otf,.ttc" : "";
  const result = await api(
    `/api/pick?mode=${kind === "dir" ? "dir" : "file"}&title=${encodeURIComponent(PICK_TITLES[kind] || "انتخاب")}&ext=${encodeURIComponent(exts)}`
  );
  if (result.ok && result.path) {
    if (kind === "font") {
      const added = await api("/api/fonts/add", { method: "POST", body: JSON.stringify({ path: result.path }) });
      if (added.ok) {
        setStatus(`فونت «${added.name}» اضافه شد؛ حالا در فهرست فونت‌ها قابل انتخاب است.`, "ok");
        await loadFonts();
      } else {
        setStatus(`افزودن فونت ناموفق بود: ${added.error || ""}`, "warn");
      }
      return;
    }
    targetInput(kind).value = result.path;
  } else if (!result.ok) {
    openBrowser(kind);
  }
}

$$("[data-pick]").forEach((button) => (button.onclick = () => pickPath(button.dataset.pick)));

/* پنجره‌ی مرور مسیر */
let browserTarget = "excel";
let browserPath = "";

async function openBrowser(kind) {
  browserTarget = kind;
  $("#browserTitle").textContent = PICK_TITLES[kind] || "انتخاب مسیر";
  $("#browserModal").classList.remove("hidden");
  await browseTo(targetInput(kind)?.value || "");
}

async function browseTo(path) {
  const result = await api(`/api/browse?path=${encodeURIComponent(path || "")}`);
  if (!result.ok) {
    $("#browserList").innerHTML = `<div class="browser-item">${result.error}</div>`;
    return;
  }
  browserPath = result.path;
  $("#browserCurrent").value = result.path || "درایوها";
  const items = [];
  if (result.parent) items.push({ label: ".. پوشه‌ی بالاتر", path: result.parent, dir: true });
  (result.dirs || []).forEach((p) => items.push({ label: "📁 " + p.split(/[\\/]/).pop(), path: p, dir: true }));
  (result.files || []).forEach((p) => items.push({ label: "📄 " + p.split(/[\\/]/).pop(), path: p, dir: false }));
  $("#browserList").innerHTML =
    items.map((i) => `<div class="browser-item ${i.dir ? "" : "file"}" data-path="${i.path}" data-dir="${i.dir}">${i.label}</div>`).join("") ||
    `<div class="browser-item">پوشه‌ای وجود ندارد.</div>`;
}

$("#browserList").addEventListener("click", async (event) => {
  const item = event.target.closest(".browser-item");
  if (!item || !item.dataset.path) return;
  if (item.dataset.dir === "true") {
    await browseTo(item.dataset.path);
  } else {
    targetInput(browserTarget).value = item.dataset.path;
    $("#browserModal").classList.add("hidden");
  }
});
$("#browserUp").onclick = () => browseTo(browserPath.split(/[\\/]/).slice(0, -1).join("/") || browserPath);
$("#browserChoose").onclick = () => {
  targetInput(browserTarget).value = browserPath;
  $("#browserModal").classList.add("hidden");
};
$("#browserClose").onclick = () => $("#browserModal").classList.add("hidden");

/* ------------------------------------------------------ جمع‌آوری تنظیمات */

function collectOptions() {
  return {
    excel_path: $("#excelPath").value.trim(),
    psd_path: $("#psdPath").value.trim(),
    out_dir: $("#outDir").value.trim(),
    header_row: parseInt($("#headerRow").value || "1", 10),
    image_format: $("#imageFormat").value,
    jpeg_quality: parseInt($("#jpegQuality").value || "95", 10),
    pdf_mode: $("#pdfMode").value,
    pdf_also_individual: $("#pdfAlsoIndividual").checked,
    pdf_all_name: $("#pdfAllName").value.trim() || "همه-صفحات",
    pdf_dpi: parseInt($("#pdfDpi").value || "150", 10),
    csv_index: $("#csvIndex").checked,
    save_psd: $("#savePsd").checked,
    render: {
      scale: parseFloat($("#optScale").value),
      supersample: parseFloat($("#optSupersample").value),
      font_scale: parseFloat($("#optFontScale").value),
      line_height: parseFloat($("#optLineHeight").value),
      offset_x: parseFloat($("#optOffsetX").value || "0"),
      offset_y: parseFloat($("#optOffsetY").value || "0"),
      font_override: $("#optFont").value.trim() || null,
      text_color: $("#optForceColor").checked ? $("#optTextColor").value : null,
      transparent: $("#optTransparent").checked,
      background: $("#optTransparent").checked ? null : $("#optBackground").value,
      ignore_effects: $("#optIgnoreEffects").checked,
      anchor_mode: $("#optAnchorMode").value,
      wrap_text: $("#optWrap").value === "1",
    },
  };
}

function collectSettings() {
  const base = collectOptions();
  const layers = state.layers.map((layer) => {
    const map = state.layerMap[layer.id] || { mode: "token", tokens: {}, direction: "auto" };
    return {
      layer_id: layer.id,
      mode: map.mode,
      column: map.column || null,
      tokens: map.tokens || {},
      direction: map.direction || "auto",
    };
  });
  const sheets = state.sheets.map((sheet) => {
    const s = state.sheetSettings[sheet.name] || {};
    return {
      name: sheet.name,
      enabled: s.enabled !== false,
      name_column_1: s.col1 || null,
      name_column_2: s.col2 || null,
      separator: s.sep ?? "-",
      prefix: s.prefix || "",
      suffix: s.suffix || "",
      row_from: s.from || 1,
      row_to: s.to || null,
      folder: s.folder !== false,
      psd_path: s.psd || null,
      template_column: s.templateColumn || null,
    };
  });
  return { ...base, layers, sheets };
}

/* --------------------------------------------------------------- تحلیل */

async function analyze() {
  const options = collectOptions();
  if (!options.excel_path && !options.psd_path) {
    setStatus("حداقل مسیر فایل اکسل یا قالب فتوشاپ را وارد کنید.", "warn");
    showTab("files");
    return;
  }
  const button = $("#btnAnalyze");
  button.disabled = true;
  button.textContent = "در حال بررسی…";
  try {
    const result = await api("/api/analyze", { method: "POST", body: JSON.stringify(options) });
    if (!result.ok) throw new Error(result.error || "خطا در بررسی فایل‌ها");

    state.analysis = result;
    state.sheets = result.sheets || [];
    state.layers = result.layers || [];
    state.tokens = result.tokens || [];

    buildLayerMap(result);
    buildSheetSettings(result);
    renderLayers();
    renderSheets();
    renderPreviewSheetOptions();

    const hasLayers = state.layers.length > 0;
    const hasSheets = state.sheets.length > 0;
    $("#badgeLayers").textContent = hasLayers ? faNumber(state.layers.length) : "";
    $("#badgeSheets").textContent = hasSheets ? faNumber(state.sheets.length) : "";
    setTabEnabled("layers", hasLayers);
    setTabEnabled("sheets", hasSheets);
    setTabEnabled("settings", hasLayers || hasSheets);
    setTabEnabled("run", hasSheets);
    $("#layersHint").textContent = hasLayers
      ? `${faNumber(state.layers.length)} لایه‌ی متنی و ${faNumber(state.tokens.length)} پلیس‌هولدر پیدا شد.`
      : "";

    const messages = [];
    if (hasLayers) {
      messages.push(`<b>${faNumber(state.layers.length)}</b> لایه‌ی متنی و <b>${faNumber(state.tokens.length)}</b> پلیس‌هولدر پیدا شد.`);
    } else {
      messages.push("لایه‌ی متنی پیدا نشد؛ مطمئن شوید متن‌های قالب واقعاً «لایه‌ی متنی» فتوشاپ باشند.");
    }
    if (hasSheets) {
      const totalRows = state.sheets.reduce((sum, s) => sum + s.row_count, 0);
      messages.push(`<b>${faNumber(state.sheets.length)}</b> شیت با مجموع <b>${faNumber(totalRows)}</b> ردیف داده.`);
    }
    (result.warnings || []).forEach((w) => messages.push(`<span style="color:#b45309">⚠ ${w}</span>`));
    Object.values(result.fonts || {})
      .filter((f) => !f.ok)
      .forEach((f) => messages.push(`<span style="color:#b45309">⚠ فونت «${f.family}» روی سیستم نیست یا نویسه‌ها را پشتیبانی نمی‌کند؛ فونت جانشین استفاده می‌شود.</span>`));

    setStatus(messages.join("<br/>"), hasLayers && hasSheets ? "ok" : "warn");

    if ((!hasLayers && hasSheets) || (hasLayers && !hasSheets)) {
      showTab(hasLayers ? "layers" : "files");
    } else if (hasLayers) {
      showTab("layers");
    }
  } catch (error) {
    setStatus("خطا: " + error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = "بررسی و بارگذاری فایل‌ها";
  }
}

function columnTitles() {
  const names = [];
  state.sheets.forEach((sheet) => {
    (sheet.columns || []).forEach((column) => {
      const title = column.unique_title || column.title;
      if (title && !names.includes(title)) names.push(title);
    });
  });
  return names;
}

function columnTitleFromKey(key) {
  if (key === null || key === undefined || key === "") return null;
  const text = String(key).trim();
  if (!/^[0-9]+$/.test(text)) return text;
  const index = parseInt(text, 10);
  for (const sheet of state.sheets) {
    const column = (sheet.columns || []).find((c) => c.index === index);
    if (column) return column.unique_title || column.title;
  }
  return text;
}

function buildLayerMap(result) {
  const columns = columnTitles();
  state.layerMap = {};
  state.layers.forEach((layer) => {
    const tokens = {};
    (layer.tokens || []).forEach((token) => {
      const auto = (result.token_map || {})[token];
      tokens[token] = auto ? columnTitleFromKey(auto) : "";
    });
    state.layerMap[layer.id] = {
      mode: (layer.tokens || []).length ? "token" : "skip",
      column: columns.length ? columns[0] : null,
      tokens,
      direction: "auto",
    };
  });
}

function buildSheetSettings(result) {
  state.sheetSettings = {};
  const suggestions = {};
  (result.suggested_sheets || []).forEach((s) => (suggestions[s.name] = s));
  state.sheets.forEach((sheet) => {
    const suggestion = suggestions[sheet.name] || {};
    state.sheetSettings[sheet.name] = {
      enabled: true,
      col1: suggestion.name_column_1 || null,
      col2: suggestion.name_column_2 || null,
      sep: "-",
      prefix: "",
      suffix: "",
      from: 1,
      to: null,
      folder: true,
      psd: "",
      templateColumn: "",
    };
  });
}

/* -------------------------------------------------------- نمایش لایه‌ها */

function columnOptions(selected, allowEmpty = true) {
  const titles = columnTitles();
  const options = allowEmpty ? [`<option value="">— بدون نگاشت —</option>`] : [];
  titles.forEach((title) => {
    const isSelected = String(selected || "") === title ? " selected" : "";
    options.push(`<option value="${title}"${isSelected}>${title}</option>`);
  });
  if (selected && !titles.includes(selected)) {
    options.push(`<option value="${selected}" selected>${selected}</option>`);
  }
  return options.join("");
}

function highlightText(text, layerId) {
  const escaped = (text || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return escaped.replace(/\{\{\s*([^{}]+?)\s*\}\}|\{\s*([^{}]+?)\s*\}/g, (match, a, b) => {
    const token = (a || b || "").trim();
    const mapped = state.layerMap[layerId]?.tokens?.[token];
    return `<span class="token ${mapped ? "mapped" : "unmapped"}">${match}</span>`;
  });
}

const MODE_LABELS = [
  ["token", "جایگزینی پلیس‌هولدر"],
  ["whole", "کل متن = یک ستون"],
  ["skip", "دست نزن"],
];

function renderLayers() {
  const container = $("#layerList");
  container.innerHTML = "";
  if (!state.layers.length) {
    container.innerHTML = `<div class="status warn">لایه‌ی متنی پیدا نشد.</div>`;
    return;
  }

  state.layers.forEach((layer) => {
    const map = state.layerMap[layer.id];
    const card = document.createElement("div");
    card.className = "layer-card";

    const tokenRows = (layer.tokens || [])
      .map(
        (token) => `
        <div class="token-row">
          <span class="token ${map.tokens[token] ? "mapped" : "unmapped"}">{{${token}}}</span>
          <span class="arrow">←</span>
          <select data-token="${token}" data-layer="${layer.id}">${columnOptions(map.tokens[token])}</select>
        </div>`
      )
      .join("");

    card.innerHTML = `
      <div class="layer-head">
        <div>
          <div class="layer-name">${layer.name}${layer.visible ? "" : ' <span class="badge">پنهان</span>'}</div>
          <div class="layer-sub">${layer.path || ""}${layer.fonts?.length ? " • فونت: " + layer.fonts.join("، ") : ""}</div>
        </div>
        <div class="segmented">
          ${MODE_LABELS.map(
            ([value, label]) =>
              `<label><input type="radio" name="mode-${layer.id}" value="${value}" ${
                map.mode === value ? "checked" : ""
              }/><span>${label}</span></label>`
          ).join("")}
        </div>
      </div>
      <div class="layer-body">
        <div class="layer-text">${highlightText(layer.text, layer.id) || "<span class='layer-sub'>— خالی —</span>"}</div>
        ${tokenRows || `<div class="layer-sub">این لایه پلیس‌هولدر ندارد؛ می‌توانید حالت «کل متن = یک ستون» را انتخاب کنید.</div>`}
        <div class="row">
          <label class="inline-field" data-whole="${layer.id}" style="display:${map.mode === "whole" ? "inline-flex" : "none"}">
            ستون مقدار: <select data-wholecol="${layer.id}">${columnOptions(map.column, false)}</select>
          </label>
          <span class="spacer"></span>
          <label class="inline-field">جهت متن:
            <select data-dir="${layer.id}">
              <option value="auto" ${(map.direction || "auto") === "auto" ? "selected" : ""}>خودکار</option>
              <option value="rtl" ${map.direction === "rtl" ? "selected" : ""}>راست‌به‌چپ</option>
              <option value="ltr" ${map.direction === "ltr" ? "selected" : ""}>چپ‌به‌راست</option>
            </select>
          </label>
        </div>
      </div>`;
    container.appendChild(card);
  });

  container.querySelectorAll("select[data-token]").forEach((select) => {
    select.onchange = () => {
      state.layerMap[select.dataset.layer].tokens[select.dataset.token] = select.value;
      const chip = select.parentElement.querySelector(".token");
      const mapped = !!select.value;
      chip.classList.toggle("mapped", mapped);
      chip.classList.toggle("unmapped", !mapped);
    };
  });
  container.querySelectorAll("input[type=radio]").forEach((radio) => {
    radio.onchange = () => {
      const layerId = radio.name.replace("mode-", "");
      state.layerMap[layerId].mode = radio.value;
      const wholeLabel = container.querySelector(`[data-whole="${layerId}"]`);
      if (wholeLabel) wholeLabel.style.display = radio.value === "whole" ? "inline-flex" : "none";
    };
  });
  container.querySelectorAll("select[data-wholecol]").forEach((select) => {
    select.onchange = () => (state.layerMap[select.dataset.wholecol].column = select.value);
  });
  container.querySelectorAll("select[data-dir]").forEach((select) => {
    select.onchange = () => (state.layerMap[select.dataset.dir].direction = select.value);
  });
}

/* -------------------------------------------------------- نمایش شیت‌ها */

function sampleName(sheet, settings) {
  const col1 = sheet.columns.find((c) => c.letter === settings.col1);
  const col2 = sheet.columns.find((c) => c.letter === settings.col2);
  const row = (sheet.sample_rows && sheet.sample_rows[0]) || [];
  const value1 = col1 ? row[col1.index - 1] || "" : "";
  const value2 = col2 ? row[col2.index - 1] || "" : "";
  const parts = [value1, value2].filter((v) => v);
  const joined = parts.length > 1 ? parts.join(settings.sep ?? "-") : parts[0] || "ردیف-۱";
  return (settings.prefix || "") + joined + (settings.suffix || "");
}

function renderSheets() {
  const tbody = $("#sheetTable tbody");
  tbody.innerHTML = "";

  state.sheets.forEach((sheet) => {
    const settings = state.sheetSettings[sheet.name];

    const columnSelect = (selected, key) =>
      `<select data-sheet="${sheet.name}" data-key="${key}">
        <option value="">— ندارد —</option>
        ${sheet.columns
          .map(
            (column) =>
              `<option value="${column.letter}"${String(selected) === column.letter ? " selected" : ""}>${column.letter} — ${column.unique_title}</option>`
          )
          .join("")}
      </select>`;

    const row = document.createElement("tr");
    row.innerHTML = `
      <td style="text-align:center"><input type="checkbox" data-sheet="${sheet.name}" data-key="enabled" ${settings.enabled !== false ? "checked" : ""}/></td>
      <td><b>${sheet.name}</b></td>
      <td class="layer-sub">${faNumber(settings.from)} تا ${faNumber(settings.to || sheet.row_count)}</td>
      <td>${faNumber(sheet.row_count)}</td>
      <td>${columnSelect(settings.col1, "col1")}</td>
      <td>${columnSelect(settings.col2, "col2")}</td>
      <td><input class="sep" type="text" data-sheet="${sheet.name}" data-key="sep" value="${settings.sep ?? "-"}" /></td>
      <td>
        <input type="text" placeholder="پیشوند" data-sheet="${sheet.name}" data-key="prefix" value="${settings.prefix || ""}" style="min-width:74px;width:74px"/>
        <input type="text" placeholder="پسوند" data-sheet="${sheet.name}" data-key="suffix" value="${settings.suffix || ""}" style="min-width:74px;width:74px"/>
      </td>
      <td>
        <input type="text" placeholder="مثلاً قالب-ویژه.psd" data-sheet="${sheet.name}" data-key="psd" value="${settings.psd || ""}" style="min-width:126px;width:126px"/>
        <select data-sheet="${sheet.name}" data-key="templateColumn" style="min-width:96px;width:96px">
          <option value="">ستون قالب: ندارد</option>
          ${sheet.columns
            .map((c) => `<option value="${c.letter}"${String(settings.templateColumn) === c.letter ? " selected" : ""}>${c.letter} — ${c.unique_title}</option>`)
            .join("")}
        </select>
      </td>
      <td style="text-align:center"><input type="checkbox" data-sheet="${sheet.name}" data-key="folder" ${settings.folder !== false ? "checked" : ""}/></td>
    `;
    tbody.appendChild(row);

    const rangeRow = document.createElement("tr");
    rangeRow.className = "range-row";
    rangeRow.innerHTML = `
      <td colspan="10">
        بازه‌ی ردیف‌ها: از <input type="number" min="1" value="${settings.from || 1}" data-sheet="${sheet.name}" data-key="from" />
        تا <input type="number" min="1" placeholder="${faNumber(sheet.row_count)}" value="${settings.to || ""}" data-sheet="${sheet.name}" data-key="to" />
        <span style="margin-inline-start:14px">نمونه‌ی نام فایل: <code>${sampleName(sheet, settings)}</code></span>
      </td>`;
    tbody.appendChild(rangeRow);
  });

  tbody.querySelectorAll("input, select").forEach((element) => {
    element.onchange = () => {
      const settings = state.sheetSettings[element.dataset.sheet];
      const key = element.dataset.key;
      if (element.type === "checkbox") settings[key] = element.checked;
      else if (key === "from" || key === "to") settings[key] = element.value ? parseInt(element.value, 10) : null;
      else settings[key] = element.value;

      const sheet = state.sheets.find((s) => s.name === element.dataset.sheet);
      if (sheet) {
        const cell = element.closest("tr").nextElementSibling?.querySelector("code");
        if (cell) cell.textContent = sampleName(sheet, settings);
      }
    };
  });

  $("#sameNameColumns").onchange = (event) => {
    if (!event.target.checked || !state.sheets.length) return;
    const source = state.sheetSettings[state.sheets[0].name];
    state.sheets.slice(1).forEach((sheet) => {
      const settings = state.sheetSettings[sheet.name];
      settings.col1 = source.col1;
      settings.col2 = source.col2;
      settings.sep = source.sep;
      settings.prefix = source.prefix;
      settings.suffix = source.suffix;
    });
    renderSheets();
  };
}

/* ------------------------------------------------------------ پیش‌نمایش */

function renderPreviewSheetOptions() {
  $("#previewSheet").innerHTML = state.sheets
    .map((sheet) => `<option value="${sheet.name}">${sheet.name} (${faNumber(sheet.row_count)} ردیف)</option>`)
    .join("");
}

const truncate = (text, length = 66) => {
  const value = (text || "").replace(/\r?\n/g, " ⏎ ");
  return value.length > length ? value.slice(0, length) + "…" : value;
};

async function preview() {
  if (!state.sheets.length) {
    setStatus("اول فایل‌ها را بررسی کنید.", "warn");
    showTab("files");
    return;
  }
  const button = $("#btnPreview");
  button.disabled = true;
  button.textContent = "در حال ساخت…";
  try {
    const payload = collectSettings();
    payload.sheet = $("#previewSheet").value;
    payload.row = Math.max(0, parseInt($("#previewRow").value || "1", 10) - 1);
    const result = await api("/api/preview", { method: "POST", body: JSON.stringify(payload) });
    if (!result.ok) throw new Error(result.error || "خطا در پیش‌نمایش");

    $("#previewBox").innerHTML = `<img src="${result.image}" alt="پیش‌نمایش" />`;
    const details = (result.details || [])
      .map((item) => `<li><b>${item.layer}</b>: «${truncate(item.before, 44)}» ← «${truncate(item.after, 44)}»</li>`)
      .join("");
    const warnings = (result.report?.warnings || []).map((w) => `<li>${w}</li>`).join("");
    const missingFonts = (result.report?.layers || [])
      .filter((l) => l.font_missing)
      .map((l) => `<li>لایه «${l.layer}»: فونت قالب پیدا نشد (${l.font_used || "جانشین"})</li>`)
      .join("");

    $("#previewInfo").className = "status";
    $("#previewInfo").innerHTML = `
      ابعاد خروجی: <b>${faNumber(result.size[0])} × ${faNumber(result.size[1])}</b> پیکسل —
      تعداد جایگزینی: <b>${faNumber((result.details || []).length)}</b>
      <ul>${details || "<li>هیچ متنی جایگزین نشد؛ نگاشت ستون‌ها را بررسی کنید.</li>"}</ul>
      ${warnings || missingFonts ? `<div style="color:#b45309;margin-top:6px">هشدارها:</div><ul>${warnings}${missingFonts}</ul>` : ""}
    `;
  } catch (error) {
    setStatus("خطا در پیش‌نمایش: " + error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = "پیش‌نمایش";
  }
}

/* --------------------------------------------------------------- اجرا */

async function start() {
  const enabled = state.sheets.filter((sheet) => state.sheetSettings[sheet.name].enabled !== false);
  if (!enabled.length) {
    setStatus("هیچ شیتی فعال نیست.", "warn");
    showTab("sheets");
    return;
  }
  const payload = collectSettings();
  if (!payload.out_dir) {
    setStatus("پوشه‌ی مقصد خروجی را انتخاب کنید.", "warn");
    showTab("files");
    return;
  }
  try {
    const result = await api("/api/start", { method: "POST", body: JSON.stringify(payload) });
    if (!result.ok) throw new Error(result.error || "شروع نشد");
    $("#btnStart").disabled = true;
    $("#btnStop").classList.remove("hidden");
    $("#errorBox").classList.add("hidden");
    $("#logBox").textContent = "شروع عملیات…\n";
    pollStatus();
  } catch (error) {
    setStatus("خطا: " + error.message, "error");
  }
}

async function pollStatus() {
  clearTimeout(state.pollTimer);
  try {
    const status = await api("/api/status");
    const total = status.total || 0;
    const done = status.done || 0;
    const percent = total ? Math.round((done / total) * 100) : 0;
    $("#progressBar").style.width = percent + "%";
    $("#progressPercent").textContent = faNumber(percent) + "٪";
    $("#progressText").textContent =
      status.state === "running"
        ? `در حال تولید… (${faNumber(done)} از ${faNumber(total)}) — شیت: ${status.sheet || "-"} / ردیف: ${faNumber(status.row || 0)}`
        : status.state === "done"
        ? `پایان یافت؛ ${faNumber(status.produced_count || done)} فایل ساخته شد.`
        : status.state === "stopped"
        ? "عملیات متوقف شد."
        : status.state === "error"
        ? "خطا در اجرای عملیات."
        : "آماده";

    if (status.log) {
      $("#logBox").textContent = status.log.join("\n");
      $("#logBox").scrollTop = $("#logBox").scrollHeight;
    }
    if (status.errors && status.errors.length) {
      $("#errorBox").classList.remove("hidden");
      $("#errorBox").innerHTML =
        `<b>${faNumber(status.errors.length)} خطا رخ داد:</b><ul>` +
        status.errors.slice(0, 40).map((e) => `<li>شیت «${e.sheet}» ردیف ${faNumber(e.row)}: ${e.error}</li>`).join("") +
        `</ul>`;
    }
    if (status.state === "running") {
      state.pollTimer = setTimeout(pollStatus, 900);
    } else {
      $("#btnStart").disabled = false;
      $("#btnStop").classList.add("hidden");
      if (status.state === "done") setStatus(`تولید با موفقیت انجام شد. خروجی‌ها در: <code>${status.out_dir || "-"}</code>`, "ok");
    }
  } catch (error) {
    state.pollTimer = setTimeout(pollStatus, 2000);
  }
}

/* ------------------------------------------------------------ رویدادها */

$("#btnAnalyze").onclick = analyze;
$("#btnPreview").onclick = preview;
$("#btnStart").onclick = start;
$("#btnStop").onclick = async () => {
  await api("/api/stop", { method: "POST", body: "{}" });
  setStatus("درخواست توقف ارسال شد.", "warn");
};
$("#btnOpenOut").onclick = () => {
  const path = $("#outDir").value.trim();
  if (path) api(`/api/open?path=${encodeURIComponent(path)}`);
};
$("#btnHelp").onclick = () => $("#helpModal").classList.remove("hidden");
$("#helpClose").onclick = () => $("#helpModal").classList.add("hidden");
function syncFormatOptions() {
  const format = $("#imageFormat").value;
  const isPdf = format === "pdf";
  const mode = $("#pdfMode").value;
  $("#qualityWrap").classList.toggle("hidden", format !== "jpg");
  $("#pdfWrap").classList.toggle("hidden", !isPdf);
  $("#pdfDpiWrap").classList.toggle("hidden", !isPdf);
  $("#pdfAllNameWrap").classList.toggle("hidden", !(isPdf && mode === "all"));
  $("#pdfAlsoWrap").classList.toggle("hidden", !(isPdf && mode !== "each"));
}
$("#imageFormat").onchange = syncFormatOptions;
$("#pdfMode").onchange = syncFormatOptions;
$("#optFontScale").oninput = (event) => ($("#fontScaleValue").textContent = event.target.value);
$("#optLineHeight").oninput = (event) => ($("#lineHeightValue").textContent = event.target.value);

$("#btnSaveSettings").onclick = async () => {
  const result = await api("/api/save-settings", { method: "POST", body: JSON.stringify(collectSettings()) });
  if (result.ok) setStatus(`تنظیمات ذخیره شد: <code>${result.path}</code>`, "ok");
  else setStatus("ذخیره‌ی تنظیمات ناموفق بود.", "error");
};

async function fillFromSettings(data) {
  $("#excelPath").value = data.excel_path || "";
  $("#psdPath").value = data.psd_path || "";
  $("#outDir").value = data.out_dir || "";
  $("#headerRow").value = data.header_row || 1;
  $("#imageFormat").value = data.image_format || "png";
  $("#savePsd").checked = !!data.save_psd;
  $("#jpegQuality").value = data.jpeg_quality || 95;
  $("#pdfMode").value = data.pdf_mode || "sheet";
  $("#pdfAlsoIndividual").checked = !!data.pdf_also_individual;
  $("#pdfAllName").value = data.pdf_all_name || "همه-صفحات";
  $("#pdfDpi").value = data.pdf_dpi || 150;
  $("#csvIndex").checked = !!data.csv_index;
  const render = data.render || {};
  $("#optScale").value = String(render.scale ?? 1);
  $("#optSupersample").value = String(render.supersample ?? 2);
  $("#optFontScale").value = render.font_scale ?? 1;
  $("#fontScaleValue").textContent = render.font_scale ?? 1;
  $("#optLineHeight").value = render.line_height ?? 1;
  $("#lineHeightValue").textContent = render.line_height ?? 1;
  $("#optOffsetX").value = render.offset_x ?? 0;
  $("#optOffsetY").value = render.offset_y ?? 0;
  $("#optFont").value = render.font_override || "";
  $("#optForceColor").checked = !!render.text_color;
  $("#optTextColor").value = render.text_color || "#ffffff";
  $("#optTransparent").checked = !!render.transparent;
  $("#optBackground").value = render.background || "#ffffff";
  $("#optIgnoreEffects").checked = !!render.ignore_effects;
  if (render.anchor_mode) $("#optAnchorMode").value = render.anchor_mode;
  if (render.wrap_text !== undefined) $("#optWrap").value = render.wrap_text ? "1" : "0";
  syncFormatOptions();
}

$("#btnLoadSettings").onclick = async () => {
  const result = await api("/api/settings");
  if (!result.settings) {
    setStatus("تنظیمات ذخیره‌شده‌ای وجود ندارد.", "warn");
    return;
  }
  await fillFromSettings(result.settings);
  setStatus("تنظیمات بازخوانی شد؛ در حال بررسی فایل‌ها…", "ok");
  analyze();
};

/* -------------------------------------------------------------- فونت‌ها */

async function loadFonts() {
  try {
    const result = await api("/api/fonts");
    $("#fontList").innerHTML = (result.fonts || []).map((f) => `<option value="${f}"></option>`).join("");
  } catch (e) {
    /* بی‌اهمیت */
  }
}

/* ------------------------------------------------------------ راه‌اندازی */

(async () => {
  await loadFonts();
  try {
    const result = await api("/api/settings");
    if (result.settings) {
      await fillFromSettings(result.settings);
      setStatus("تنظیمات ذخیره‌شده بارگذاری شد؛ در حال بررسی فایل‌ها…", "ok");
      analyze();
    }
  } catch (error) {
    /* بی‌اهمیت */
  }
  renderPreviewSheetOptions();
})();
