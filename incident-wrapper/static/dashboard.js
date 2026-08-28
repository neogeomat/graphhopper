/* GraphHopper dashboard — MapLibre GL + Mapterhorn 3D terrain.
 * Layer stack (bottom -> top): basemap, overlay-*, hillshade,
 * incidents-fill/outline, draft-*, route-casing/route-line.
 * 'hillshade' always exists, so overlays insert with beforeId='hillshade'.
 */

// ---- tile sources -------------------------------------------------------
const MAPTERHORN = {
  tiles: ['https://tiles.mapterhorn.com/{z}/{x}/{y}.webp'],
  encoding: 'terrarium',
  tileSize: 512,
  maxzoom: 12,                   // verified: z13+ returns 404
  attribution: '<a href="https://mapterhorn.com/attribution" target="_blank">Mapterhorn</a>'
};

const OSM_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a> contributors';

const BASEMAPS = {
  esri_imagery: {
    name: 'Esri World Imagery',
    tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
    tileSize: 256, maxzoom: 19, attribution: 'Esri, Maxar, Earthstar Geographics'
  },
  osm: {
    name: 'OpenStreetMap',
    tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
    tileSize: 256, maxzoom: 19, attribution: OSM_ATTR
  },
  opentopo: {
    name: 'OpenTopoMap',
    tiles: ['https://a.tile.opentopomap.org/{z}/{x}/{y}.png',
            'https://b.tile.opentopomap.org/{z}/{x}/{y}.png',
            'https://c.tile.opentopomap.org/{z}/{x}/{y}.png'],
    tileSize: 256, maxzoom: 17, attribution: OSM_ATTR + ', SRTM | <a href="https://opentopomap.org" target="_blank">OpenTopoMap</a> (CC-BY-SA)'
  }
};

const LS_KEY = 'gh_dashboard_layers_v1';
const LS_BASE = 'gh_dashboard_base';
const EMPTY_FC = { type: 'FeatureCollection', features: [] };

// Vector (style-JSON) basemaps. Unlike raster presets these replace the whole
// style, so switching to/from them goes through rebuildStyle().
// Baato is fetched through the wrapper's proxy so BAATO_KEY never reaches the
// browser (the raw style embeds the key in one of its vector tile URLs).
const STYLE_BASEMAPS = {
  baato_breeze: {
    name: 'Baato Breeze', kind: 'style', needsKey: 'baato',
    url: function () { return '/baato/style/breeze'; }
  },
  openfreemap_liberty: {
    name: 'OpenFreeMap Liberty', kind: 'style',
    url: function () { return 'https://tiles.openfreemap.org/styles/liberty'; }
  }
};
Object.keys(STYLE_BASEMAPS).forEach(function (k) { BASEMAPS[k] = STYLE_BASEMAPS[k]; });

const DEFAULT_BASE = 'baato_breeze';       // falls back if the key is missing/invalid
const SAFE_BASE = 'esri_imagery';

// ---- state --------------------------------------------------------------
// The default base is a vector style whose key only arrives from /config, so the
// map boots with NO raster basemap rather than downloading a basemap we are about
// to throw away. Returning users who last picked a raster base boot straight into it.
function initialRasterBase() {
  try {
    const saved = localStorage.getItem(LS_BASE);
    if (saved && BASEMAPS[saved]) return BASEMAPS[saved].kind === 'style' ? null : saved;
  } catch (e) {}
  return BASEMAPS[DEFAULT_BASE] && BASEMAPS[DEFAULT_BASE].kind === 'style' ? null : SAFE_BASE;
}

let activeBase = initialRasterBase();   // may be null until the real base resolves
let overlays = [];               // [{id,name,kind,url,tileSize,maxzoom,attribution,encoding,visible,opacity}]
let terrainSourceId = 'dem-mapterhorn';
let currentVector = false;       // is the active basemap a vector style?
let baatoConfigured = false;     // does the server hold a BAATO_KEY?
let lastRouteGeoJSON = null;     // survives a style rebuild

function loadOverlays() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (raw) overlays = JSON.parse(raw) || [];
  } catch (e) { overlays = []; }
  // anything restored from storage is by definition saved
  overlays.forEach(function (o) { o.saved = true; });
}
// Only opted-in layers are written; session-only ones stay in memory.
function saveOverlays() {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(overlays.filter(function (o) { return o.saved; })));
  } catch (e) {}
}
loadOverlays();

// ---- style --------------------------------------------------------------
function baseSourceDef(def) {
  return {
    type: 'raster', tiles: def.tiles, tileSize: def.tileSize,
    maxzoom: def.maxzoom, attribution: def.attribution
  };
}

function buildStyle(vs) {
  const sources = {}, layers = [];
  if (vs) {
    // vector style supplies its own sources + layers; ours stack on top
    Object.keys(vs.sources || {}).forEach(function (k) { sources[k] = vs.sources[k]; });
    (vs.layers || []).forEach(function (l) { layers.push(l); });
  } else if (activeBase && BASEMAPS[activeBase] && BASEMAPS[activeBase].tiles) {
    sources.basemap = baseSourceDef(BASEMAPS[activeBase]);
    layers.push({ id: 'basemap', type: 'raster', source: 'basemap' });
  }

  sources['dem-mapterhorn'] = {
    type: 'raster-dem', tiles: MAPTERHORN.tiles, encoding: MAPTERHORN.encoding,
    tileSize: MAPTERHORN.tileSize, maxzoom: MAPTERHORN.maxzoom, attribution: MAPTERHORN.attribution
  };
  sources['dem-hillshade'] = {
    type: 'raster-dem', tiles: MAPTERHORN.tiles, encoding: MAPTERHORN.encoding,
    tileSize: MAPTERHORN.tileSize, maxzoom: MAPTERHORN.maxzoom
  };
  sources.incidents = { type: 'geojson', data: EMPTY_FC };
  sources.draft = { type: 'geojson', data: EMPTY_FC };
  sources.route = { type: 'geojson', data: EMPTY_FC };

  layers.push(
    { id: 'hillshade', type: 'hillshade', source: 'dem-hillshade',
      paint: { 'hillshade-exaggeration': 0.45, 'hillshade-shadow-color': '#2c3e50' } },
    { id: 'incidents-fill', type: 'fill', source: 'incidents',
      paint: { 'fill-color': incidentColorExpr(), 'fill-opacity': 0.35 } },
    { id: 'incidents-outline', type: 'line', source: 'incidents',
      paint: { 'line-color': incidentColorExpr(), 'line-width': 2 } },
    { id: 'draft-fill', type: 'fill', source: 'draft',
      filter: ['==', ['geometry-type'], 'Polygon'],
      paint: { 'fill-color': '#00b894', 'fill-opacity': 0.25 } },
    { id: 'draft-line', type: 'line', source: 'draft',
      filter: ['!=', ['geometry-type'], 'Point'],
      paint: { 'line-color': '#00b894', 'line-width': 2, 'line-dasharray': [2, 1] } },
    { id: 'draft-vertex', type: 'circle', source: 'draft',
      filter: ['==', ['geometry-type'], 'Point'],
      paint: { 'circle-radius': 5, 'circle-color': '#fff', 'circle-stroke-color': '#00b894', 'circle-stroke-width': 2 } },
    { id: 'route-casing', type: 'line', source: 'route',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': '#ffffff', 'line-width': 8, 'line-opacity': 0.9 } },
    { id: 'route-line', type: 'line', source: 'route',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': '#0984e3', 'line-width': 5 } }
  );

  const style = { version: 8, sources: sources, layers: layers };
  if (vs) {
    if (vs.glyphs) style.glyphs = vs.glyphs;      // required for label layers
    if (vs.sprite) style.sprite = vs.sprite;      // required for icon layers
    if (vs.light) style.light = vs.light;
    if (vs.transition) style.transition = vs.transition;
  }
  return style;
}

function incidentColorExpr() {
  return ['case', ['==', ['get', 'active'], false], '#95a5a6',
    ['match', ['get', 'type'],
      'ROAD_CLOSURE', '#d63031',
      'ACCIDENT', '#e17055',
      'CONSTRUCTION', '#f9ca24',
      'HAZARD', '#6c5ce7',
      '#636e72']];
}

// ---- map ----------------------------------------------------------------
const map = new maplibregl.Map({
  container: 'map',
  style: buildStyle(),
  center: [85.3240, 27.7172],
  zoom: 12,
  pitch: 60,        // tilt, for the 3D terrain
  bearing: 0,       // north up — no rotation
  maxPitch: 85,
  hash: false
});
// panels occupy both top corners, so map controls live along the bottom
map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'bottom-right');
map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: 'metric' }), 'bottom-right');
map.addControl(new maplibregl.GlobeControl(), 'bottom-right');

let styleReady = false;

map.on('load', async function () {
  styleReady = true;
  // registered here: BasemapSwitcher.prototype.onAdd is assigned further down,
  // so adding the control at script top level would run before it exists.
  map.addControl(new BasemapSwitcher(), 'bottom-left');
  applyTerrain();
  restoreOverlayLayers();
  renderBaseList();
  renderTerrainSourceList();
  renderOverlayList();
  loadIncidents();
  bindLayerFormUI();
  renderWaypoints();
  updateHint();
  await initBaatoKey();
  await initDefaultBasemap();
});

// ---- terrain ------------------------------------------------------------
function applyTerrain() {
  if (!styleReady) return;
  const on = document.getElementById('terrain-on').checked;
  const exag = parseFloat(document.getElementById('exag').value);
  if (on) {
    map.setTerrain({ source: terrainSourceId, exaggeration: exag });
  } else {
    map.setTerrain(null);
  }
}

function setHillshade() {
  if (!styleReady) return;
  const on = document.getElementById('hillshade-on').checked;
  map.setLayoutProperty('hillshade', 'visibility', on ? 'visible' : 'none');
}

// ---- base layer swap ----------------------------------------------------
function baseNotice(msg) {
  const el = document.getElementById('base-notice');
  if (!el) return;
  el.textContent = msg || '';
  el.style.display = msg ? 'block' : 'none';
}

function resolveStyleUrl(def) {
  if (def.needsKey === 'baato' && !baatoConfigured) return null;
  return def.url();
}

// Re-applies everything that a setStyle() call destroys.
function rebuildStyle(vs) {
  return new Promise(function (resolve) {
    currentVector = !!vs;
    // Calling setStyle() while terrain is active crashes MapLibre internally
    // ("cannot read properties of undefined (reading 'shaderPreludeCode')"),
    // so drop terrain first and re-apply it once the new style is loaded.
    if (map.getTerrain()) map.setTerrain(null);

    let done = false;
    function finish() {
      if (done) return;
      done = true;
      map.off('style.load', finish);
      map.off('idle', finish);
      restoreOverlayLayers();
      setIncidentSourceData();
      if (lastRouteGeoJSON && map.getSource('route')) map.getSource('route').setData(lastRouteGeoJSON);
      if (drawing) updateDraft();
      applyTerrain();
      setHillshade();
      resolve();
    }
    // 'style.load' is the documented hook; 'idle' is a belt-and-braces fallback.
    map.on('style.load', finish);
    map.on('idle', finish);
    map.setStyle(buildStyle(vs));
  });
}

async function setBasemap(id, opts) {
  const def = BASEMAPS[id];
  if (!def || !styleReady) return false;
  const quiet = !!(opts && opts.quiet);

  if (def.kind === 'style') {
    const url = resolveStyleUrl(def);
    if (!url) {
      if (!quiet) baseNotice(def.name + ' needs an API key — paste one below.');
      renderBaseList();
      return false;
    }
    let vs;
    try {
      const r = await fetch(url);
      if (!r.ok) throw new Error('HTTP ' + r.status);
      vs = await r.json();
      if (!vs || !vs.layers) throw new Error('not a MapLibre style');
    } catch (e) {
      if (!quiet) baseNotice(def.name + ' unavailable (' + e.message + ').');
      renderBaseList();
      return false;
    }
    activeBase = id;
    await rebuildStyle(vs);
  } else if (currentVector) {
    // leaving a vector style: the whole style must be rebuilt
    activeBase = id;
    await rebuildStyle(null);
  } else {
    activeBase = id;
    if (map.getLayer('basemap')) map.removeLayer('basemap');
    if (map.getSource('basemap')) map.removeSource('basemap');
    map.addSource('basemap', baseSourceDef(def));
    const bottom = map.getStyle().layers[0];
    map.addLayer({ id: 'basemap', type: 'raster', source: 'basemap' }, bottom ? bottom.id : undefined);
  }
  try { localStorage.setItem(LS_BASE, activeBase); } catch (e) {}
  baseNotice('');
  renderBaseList();
  return true;
}

// ---- Baato availability (key stays on the server) -----------------------
async function initBaatoKey() {
  try {
    const cfg = await (await fetch('/config')).json();
    baatoConfigured = !!(cfg && cfg.baato_configured);
  } catch (e) {
    baatoConfigured = false;
  }
}

// Boot: try the preferred default, fall back to a working raster base.
async function initDefaultBasemap() {
  let want = DEFAULT_BASE;
  try {
    const saved = localStorage.getItem(LS_BASE);
    if (saved && BASEMAPS[saved]) want = saved;
  } catch (e) {}
  if (want === activeBase) return;
  const ok = await setBasemap(want, { quiet: true });
  if (!ok) {
    const d = BASEMAPS[want];
    await setBasemap(SAFE_BASE, { quiet: true });     // never leave the map bare
    baseNotice((d ? d.name : want) + ' unavailable' +
      (d && d.needsKey === 'baato' && !baatoConfigured ? ' (server has no BAATO_KEY)' : '') +
      ' — using ' + BASEMAPS[SAFE_BASE].name + '.');
  }
}

function renderBaseList() {
  const el = document.getElementById('baselist');
  el.innerHTML = Object.keys(BASEMAPS).map(function (k) {
    return '<label><input type="radio" name="base" value="' + k + '"' +
      (k === activeBase ? ' checked' : '') + ' onchange="setBasemap(\'' + k + '\')"> ' +
      esc(BASEMAPS[k].name) + '</label>';
  }).join('');
  renderSwitcher();
}

// ---- on-map layers control ----------------------------------------------
function renderSwitcher() {
  const cur = document.getElementById('bs-current');
  if (cur) cur.textContent = (activeBase && BASEMAPS[activeBase]) ? BASEMAPS[activeBase].name : 'loading…';
}

function BasemapSwitcher() {}
BasemapSwitcher.prototype.onAdd = function (m) {
  const c = document.createElement('div');
  c.className = 'maplibregl-ctrl maplibregl-ctrl-group layers-ctrl';
  c.innerHTML =
    '<button type="button" id="bs-toggle" title="Layers &amp; terrain">' +
      '<span class="bs-ico">&#9707;</span>Layers &middot; <span id="bs-current">Base</span>' +
    '</button>';
  // the Layers markup lives in the page and is relocated into this control,
  // so every existing id/handler keeps working
  const content = document.getElementById('layers-content');
  if (content) c.appendChild(content);
  c.querySelector('#bs-toggle').addEventListener('click', function (e) {
    e.stopPropagation();
    c.classList.toggle('open');
  });
  this._c = c;
  return c;
};
BasemapSwitcher.prototype.onRemove = function () { this._c.remove(); };

// ---- overlays -----------------------------------------------------------
function overlaySourceDef(o) {
  if (o.kind === 'dem') {
    return { type: 'raster-dem', tiles: [o.url], encoding: o.encoding || 'terrarium',
             tileSize: o.tileSize, maxzoom: o.maxzoom, attribution: o.attribution || undefined };
  }
  return { type: 'raster', tiles: [o.url], tileSize: o.tileSize,
           maxzoom: o.maxzoom, attribution: o.attribution || undefined };
}

// DEM overlays are terrain candidates only — they get no visible raster layer.
function addOverlayLayers(o) {
  const sid = 'ov-' + o.id;
  if (map.getSource(sid)) return;
  map.addSource(sid, overlaySourceDef(o));
  if (o.kind === 'dem') return;
  map.addLayer({
    id: sid, type: 'raster', source: sid,
    layout: { visibility: o.visible ? 'visible' : 'none' },
    paint: { 'raster-opacity': o.opacity }
  }, 'hillshade');
}

function restoreOverlayLayers() {
  overlays.forEach(addOverlayLayers);
}

function addLayerFromForm() {
  const errEl = document.getElementById('l-error');
  errEl.style.display = 'none';
  const name = document.getElementById('l-name').value.trim();
  const kind = document.getElementById('l-type').value;
  let url = document.getElementById('l-url').value.trim();
  const tileSize = parseInt(document.getElementById('l-tilesize').value, 10) || 256;
  const maxzoom = parseInt(document.getElementById('l-maxzoom').value, 10) || 19;
  const attribution = document.getElementById('l-attr').value.trim();
  const encoding = document.getElementById('l-enc').value;

  function fail(msg) { errEl.textContent = msg; errEl.style.display = 'block'; }

  if (!name) return fail('Give the layer a name.');
  if (!url) return fail('URL is required.');
  if (!/^https?:\/\//i.test(url)) return fail('URL must start with http:// or https://');

  if (kind === 'wms') {
    const wmsLayers = document.getElementById('l-wms-layers').value.trim();
    if (!wmsLayers) return fail('WMS needs a layer name.');
    const sep = url.indexOf('?') === -1 ? '?' : '&';
    url = url + sep + 'service=WMS&version=1.1.1&request=GetMap&srs=EPSG:3857' +
      '&transparent=true&format=image/png&width=256&height=256' +
      '&layers=' + encodeURIComponent(wmsLayers) + '&bbox={bbox-epsg-3857}';
  } else if (!/\{z\}/.test(url) || !/\{x\}/.test(url) || !/\{y\}/.test(url)) {
    return fail('XYZ/DEM URL must contain {z}, {x} and {y}.');
  }

  const o = {
    id: 'l' + Date.now().toString(36),
    name: name, kind: kind, url: url, tileSize: tileSize, maxzoom: maxzoom,
    attribution: attribution, encoding: encoding, visible: true, opacity: 1,
    saved: document.getElementById('l-persist').checked
  };
  overlays.push(o);
  saveOverlays();
  addOverlayLayers(o);
  renderOverlayList();
  renderTerrainSourceList();
  document.getElementById('l-name').value = '';
  document.getElementById('l-url').value = '';
  document.getElementById('l-wms-layers').value = '';
}

function toggleOverlay(id) {
  const o = overlays.find(function (x) { return x.id === id; });
  if (!o || o.kind === 'dem') return;
  o.visible = !o.visible;
  saveOverlays();
  map.setLayoutProperty('ov-' + id, 'visibility', o.visible ? 'visible' : 'none');
  renderOverlayList();
}

function setOverlayOpacity(id, v) {
  const o = overlays.find(function (x) { return x.id === id; });
  if (!o || o.kind === 'dem') return;
  o.opacity = parseFloat(v);
  saveOverlays();
  map.setPaintProperty('ov-' + id, 'raster-opacity', o.opacity);
}

function removeOverlay(id) {
  const o = overlays.find(function (x) { return x.id === id; });
  if (!o) return;
  const sid = 'ov-' + id;
  if (terrainSourceId === sid) {           // fall back before pulling the source
    terrainSourceId = 'dem-mapterhorn';
    applyTerrain();
  }
  if (map.getLayer(sid)) map.removeLayer(sid);
  if (map.getSource(sid)) map.removeSource(sid);
  overlays = overlays.filter(function (x) { return x.id !== id; });
  saveOverlays();
  renderOverlayList();
  renderTerrainSourceList();
}

function useAsBase(id) {
  const o = overlays.find(function (x) { return x.id === id; });
  if (!o || o.kind === 'dem') return;
  BASEMAPS['custom-' + o.id] = {
    name: o.name + ' (added)', tiles: [o.url], tileSize: o.tileSize,
    maxzoom: o.maxzoom, attribution: o.attribution
  };
  setBasemap('custom-' + o.id);
}

function setOverlaySaved(id, saved) {
  const o = overlays.find(function (x) { return x.id === id; });
  if (!o) return;
  o.saved = saved;
  saveOverlays();
  renderOverlayList();
}

function renderOverlayList() {
  const el = document.getElementById('ovlist');
  if (!overlays.length) { el.innerHTML = '<div class="empty">None added yet.</div>'; return; }
  el.innerHTML = overlays.map(function (o) {
    const isDem = o.kind === 'dem';
    return '<div class="ov">' +
      '<div class="top">' +
        (isDem ? '' : '<input type="checkbox"' + (o.visible ? ' checked' : '') +
          ' onchange="toggleOverlay(\'' + o.id + '\')">') +
        '<span class="nm">' + esc(o.name) + '</span>' +
        '<span class="kind">' + o.kind.toUpperCase() + '</span>' +
        '<span class="sv ' + (o.saved ? 'saved">SAVED' : 'session">SESSION') + '</span>' +
      '</div>' +
      (isDem ? '' :
        '<div class="rng" style="margin-top:5px"><input type="range" min="0" max="1" step="0.05" value="' + o.opacity +
        '" oninput="setOverlayOpacity(\'' + o.id + '\', this.value)"></div>') +
      '<div class="acts">' +
        (isDem
          ? '<button onclick="setTerrainSource(\'ov-' + o.id + '\')">Use for terrain</button>'
          : '<button onclick="useAsBase(\'' + o.id + '\')">Use as base</button>') +
        (o.saved
          ? '<button onclick="setOverlaySaved(\'' + o.id + '\', false)">Forget</button>'
          : '<button onclick="setOverlaySaved(\'' + o.id + '\', true)">Save locally</button>') +
        '<button class="danger" onclick="removeOverlay(\'' + o.id + '\')">Remove</button>' +
      '</div>' +
    '</div>';
  }).join('');
}

function setTerrainSource(sid) {
  terrainSourceId = sid;
  applyTerrain();
  renderTerrainSourceList();
}

function renderTerrainSourceList() {
  const sel = document.getElementById('terrain-src');
  const opts = [{ id: 'dem-mapterhorn', name: 'Mapterhorn (terrarium, z0-12)' }];
  overlays.filter(function (o) { return o.kind === 'dem'; })
    .forEach(function (o) { opts.push({ id: 'ov-' + o.id, name: o.name }); });
  sel.innerHTML = opts.map(function (o) {
    return '<option value="' + o.id + '"' + (o.id === terrainSourceId ? ' selected' : '') + '>' + esc(o.name) + '</option>';
  }).join('');
}

function bindLayerFormUI() {
  document.getElementById('l-type').addEventListener('change', function () {
    const v = this.value;
    document.getElementById('wms-extra').style.display = (v === 'wms') ? 'block' : 'none';
    document.getElementById('dem-extra').style.display = (v === 'dem') ? 'block' : 'none';
    document.getElementById('l-url-label').textContent = (v === 'wms') ? 'WMS base URL' : 'URL template';
    document.getElementById('l-url').placeholder = (v === 'wms')
      ? 'https://host/geoserver/wms' : 'https://host/{z}/{x}/{y}.png';
    document.getElementById('l-tilesize').value = (v === 'dem') ? 512 : 256;
  });
  document.getElementById('terrain-on').addEventListener('change', applyTerrain);
  document.getElementById('hillshade-on').addEventListener('change', setHillshade);
  document.getElementById('exag').addEventListener('input', function () {
    document.getElementById('exag-val').textContent = parseFloat(this.value).toFixed(1);
    applyTerrain();
  });
  document.getElementById('pitch').addEventListener('input', function () {
    document.getElementById('pitch-val').textContent = this.value + '\u00b0';
    map.easeTo({ pitch: parseFloat(this.value), duration: 0 });
  });
  document.getElementById('terrain-src').addEventListener('change', function () {
    setTerrainSource(this.value);
  });
  map.on('pitchend', function () {
    const p = Math.round(map.getPitch());
    document.getElementById('pitch').value = p;
    document.getElementById('pitch-val').textContent = p + '\u00b0';
  });
}

// ---- UI plumbing --------------------------------------------------------
function togglePanel(which) {
  const el = document.getElementById('panel-' + which);
  if (!el) return;
  el.classList.toggle('hidden');
  const chev = el.querySelector('.chev');
  if (chev) chev.innerHTML = el.classList.contains('hidden') ? '&#9656;' : '&#9662;';
}

function openPanel(which) {
  const el = document.getElementById('panel-' + which);
  if (!el) return;
  el.classList.remove('hidden');
  const chev = el.querySelector('.chev');
  if (chev) chev.innerHTML = '&#9662;';
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}
function showError(msg) {
  const el = document.getElementById('error');
  el.textContent = msg;
  el.style.display = 'block';
}

// ---- alert box ----------------------------------------------------------
let lastAlertMsg = '';

function showAlert(msg) {
  const box = document.getElementById('alertbox');
  // auto-routing can fail repeatedly while dragging — don't stack alerts
  if (box.classList.contains('open') && msg === lastAlertMsg) return;
  lastAlertMsg = msg;
  document.getElementById('alert-msg').textContent = msg;
  box.classList.add('open');
}

function closeAlert() {
  document.getElementById('alertbox').classList.remove('open');
  lastAlertMsg = '';
}

// Turns a GraphHopper error into something actionable, and points at incidents
// when they are the likely cause.
function routeFailureMessage(raw) {
  const applying = document.getElementById('apply').checked;
  const activeCount = INCIDENTS.filter(function (i) { return i.active; }).length;
  let msg;
  if (/connection between locations not found|cannot find|not found/i.test(raw)) {
    msg = 'No route could be found between A and B.';
  } else if (/out of bounds|outside/i.test(raw)) {
    msg = 'A point lies outside the imported map area.\n\n' + raw;
  } else if (/at least 2 points/i.test(raw)) {
    msg = 'Both an origin and a destination are required.';
  } else {
    msg = raw;
  }
  if (applying && activeCount) {
    msg += '\n\n' + activeCount + ' active incident' + (activeCount === 1 ? '' : 's') +
      ' are applied as hard blocks — one may be cutting the only path. ' +
      'Untick "Apply active incidents (blocking)" to check.';
  }
  return msg;
}

// ---- routing ------------------------------------------------------------
// waypoints in travel order: index 0 = origin (A), last = destination (B),
// everything between = numbered stops.
let waypoints = [];              // [{lat, lng, marker}]
let routeTimer = null, routeSeq = 0;

function wpRole(i) {
  if (i === 0) return 'origin';
  if (i === waypoints.length - 1 && waypoints.length > 1) return 'dest';
  return 'stop';
}
function wpLabel(i) {
  const r = wpRole(i);
  return r === 'origin' ? 'A' : (r === 'dest' ? 'B' : String(i));
}

function parsePoint(v) {
  const parts = String(v).split(',').map(Number);
  if (parts.length !== 2 || !isFinite(parts[0]) || !isFinite(parts[1])) {
    throw new Error('Invalid point "' + v + '", expected lat,lon');
  }
  return { lat: parts[0], lng: parts[1] };
}

function makeMarker(w) {
  const el = document.createElement('div');
  const m = new maplibregl.Marker({ element: el, draggable: true })
    .setLngLat([w.lng, w.lat]).addTo(map);
  m.on('drag', function () {
    const ll = m.getLngLat(); w.lat = ll.lat; w.lng = ll.lng; renderWaypoints();
  });
  m.on('dragend', function () {
    const ll = m.getLngLat(); w.lat = ll.lat; w.lng = ll.lng;
    renderWaypoints(); scheduleRoute(0);
  });
  // right-click a marker to drop that point
  el.addEventListener('contextmenu', function (ev) {
    ev.preventDefault();
    ev.stopPropagation();
    removeWaypoint(waypoints.indexOf(w));
  });
  w.marker = m;
  return m;
}

function refreshMarkers() {
  waypoints.forEach(function (w, i) {
    const el = w.marker.getElement();
    el.className = 'marker-' + wpRole(i);
    el.textContent = wpLabel(i);
    el.title = wpRole(i) === 'stop' ? 'Stop ' + wpLabel(i) + ' — right-click to remove'
                                   : wpLabel(i) + ' — right-click to remove';
  });
}

function afterWaypointChange() {
  refreshMarkers();
  renderWaypoints();
  updateHint();
  if (waypoints.length < 2) {
    // not routable any more — drop the line and the summary
    routeSeq++;
    lastRouteGeoJSON = null;
    haveRoute = false;
    if (map.getSource('route')) map.getSource('route').setData(EMPTY_FC);
    document.getElementById('result').style.display = 'none';
    document.getElementById('summary').textContent = '';
    return;
  }
  scheduleRoute(0);
}

function setWaypoint(kind, ll) {
  if (kind === 'origin' && waypoints.length) {
    moveWaypoint(0, ll);
  } else if (kind === 'dest' && waypoints.length >= 2) {
    moveWaypoint(waypoints.length - 1, ll);
  } else {
    const w = { lat: ll.lat, lng: ll.lng, marker: null };
    if (kind === 'origin') waypoints.unshift(w);
    else if (kind === 'stop' && waypoints.length >= 2) waypoints.splice(waypoints.length - 1, 0, w);
    else waypoints.push(w);
    makeMarker(w);
  }
  afterWaypointChange();
}

function moveWaypoint(i, ll) {
  const w = waypoints[i];
  if (!w) return;
  w.lat = ll.lat; w.lng = ll.lng;
  w.marker.setLngLat([ll.lng, ll.lat]);
}

function removeWaypoint(i) {
  if (i < 0 || i >= waypoints.length) return;
  waypoints[i].marker.remove();
  waypoints.splice(i, 1);
  afterWaypointChange();
}

function editWaypoint(i, value) {
  try {
    moveWaypoint(i, parsePoint(value));
    document.getElementById('error').style.display = 'none';
    afterWaypointChange();
  } catch (e) {
    showError(e.message);
  }
}

function renderWaypoints() {
  const el = document.getElementById('waypoints');
  if (!waypoints.length) {
    el.innerHTML = '<div class="empty">No points yet — right-click the map.</div>';
    return;
  }
  el.innerHTML = waypoints.map(function (w, i) {
    return '<div class="wp">' +
      '<span class="wp-badge ' + wpRole(i) + '">' + wpLabel(i) + '</span>' +
      '<input type="text" value="' + w.lat.toFixed(6) + ',' + w.lng.toFixed(6) + '"' +
        ' onchange="editWaypoint(' + i + ', this.value)">' +
      '<button title="Remove this point" onclick="removeWaypoint(' + i + ')">&#10005;</button>' +
    '</div>';
  }).join('');
}

function clearPoints() {
  if (routeTimer) { clearTimeout(routeTimer); routeTimer = null; }
  routeSeq++;
  waypoints.forEach(function (w) { w.marker.remove(); });
  waypoints = [];
  lastRouteGeoJSON = null;
  haveRoute = false;
  if (map.getSource('route')) map.getSource('route').setData(EMPTY_FC);
  document.getElementById('result').style.display = 'none';
  document.getElementById('result').classList.remove('busy');
  document.getElementById('summary').textContent = '';
  document.getElementById('error').style.display = 'none';
  renderWaypoints();
  updateHint();
}

function updateHint() {
  const h = document.getElementById('hint');
  if (!waypoints.length) h.textContent = 'Right-click the map to set the origin (A).';
  else if (waypoints.length === 1) h.textContent = 'Right-click the map to set the destination (B).';
  else h.textContent = 'Right-click to add stops · drag a marker to move it · right-click a marker to remove it.';
}

// ---- right-click context menu -------------------------------------------
let ctxLngLat = null;

function showCtxMenu(pt, lngLat) {
  ctxLngLat = lngLat;
  const m = document.getElementById('ctxmenu');
  m.classList.add('open');
  // keep it inside the viewport
  const w = m.offsetWidth, h = m.offsetHeight;
  m.style.left = Math.min(pt.x, window.innerWidth - w - 8) + 'px';
  m.style.top = Math.min(pt.y, window.innerHeight - h - 8) + 'px';
}

function hideCtxMenu() {
  document.getElementById('ctxmenu').classList.remove('open');
}

function ctxAction(kind) {
  hideCtxMenu();
  if (kind === 'clear') return clearPoints();
  if (!ctxLngLat) return;
  setWaypoint(kind, { lat: ctxLngLat.lat, lng: ctxLngLat.lng });
}

map.on('contextmenu', function (e) {
  if (drawing) return;                       // don't interfere with polygon drawing
  if (e.originalEvent) e.originalEvent.preventDefault();
  showCtxMenu(e.point, e.lngLat);
});
// suppress the browser menu over the canvas
map.getContainer().addEventListener('contextmenu', function (ev) { ev.preventDefault(); });
map.on('movestart', hideCtxMenu);
document.addEventListener('click', function (ev) {
  if (!ev.target.closest('#ctxmenu')) hideCtxMenu();
});
document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') hideCtxMenu(); });

document.getElementById('profile').addEventListener('change', function () { scheduleRoute(0); });
document.getElementById('apply').addEventListener('change', function () { scheduleRoute(0); });

function scheduleRoute(delay) {
  if (routeTimer) clearTimeout(routeTimer);
  routeTimer = setTimeout(function () {
    routeTimer = null;
    if (waypoints.length >= 2) runRoute();
  }, delay === undefined ? 300 : delay);
}

let haveRoute = false;

async function runRoute(opts) {
  const shouldFit = !!(opts && opts.fit) || !haveRoute;
  const seq = ++routeSeq;
  const result = document.getElementById('result');
  document.getElementById('error').style.display = 'none';
  try {
    if (waypoints.length < 2) return;
    const url = new URL('/route', location.origin);
    waypoints.forEach(function (w) {
      url.searchParams.append('point', w.lat + ',' + w.lng);
    });
    url.searchParams.set('profile', document.getElementById('profile').value);
    url.searchParams.set('points_encoded', 'false');
    url.searchParams.set('instructions', 'true');
    url.searchParams.set('apply_incidents', String(document.getElementById('apply').checked));

    if (haveRoute) result.classList.add('busy');
    const resp = await fetch(url);
    const data = await resp.json();
    if (seq !== routeSeq) return;                 // superseded
    result.classList.remove('busy');
    if (!resp.ok || !data.paths || !data.paths.length) {
      const hints = (data.hints || []).map(function (h) { return h.message; }).join('; ');
      throw new Error((data.message || ('HTTP ' + resp.status)) + (hints ? ' — ' + hints : ''));
    }
    drawRoute(data.paths[0], shouldFit);
    closeAlert();                                  // a good route clears the warning
  } catch (e) {
    if (seq !== routeSeq) return;
    result.classList.remove('busy');
    // drop the stale line so the map never shows a route that no longer applies
    lastRouteGeoJSON = null;
    haveRoute = false;
    if (map.getSource('route')) map.getSource('route').setData(EMPTY_FC);
    document.getElementById('result').style.display = 'none';
    document.getElementById('summary').textContent = '';
    showError('Routing failed: ' + e.message);
    showAlert(routeFailureMessage(e.message));
  }
}

function drawRoute(path, fit) {
  // GraphHopper already gives [lon,lat] — no flip needed for MapLibre.
  lastRouteGeoJSON = {
    type: 'Feature', properties: {},
    geometry: { type: 'LineString', coordinates: path.points.coordinates }
  };
  map.getSource('route').setData(lastRouteGeoJSON);
  haveRoute = true;
  if (fit && path.bbox && path.bbox.length === 4) {
    map.fitBounds([[path.bbox[0], path.bbox[1]], [path.bbox[2], path.bbox[3]]],
      { padding: 70, pitch: map.getPitch(), duration: 700 });
  }

  const km = (path.distance / 1000).toFixed(2);
  const min = Math.round(path.time / 60000);
  document.getElementById('summary').textContent =
    'Distance ' + km + ' km · Time ~' + min + ' min';
  document.getElementById('result').style.display = 'block';
}

// ---- incident polygon drawing (replaces Leaflet.draw) -------------------
let drawing = false;
let draft = [];                  // [[lon,lat], ...]

function startDraw() {
  drawing = true;
  draft = [];
  hideCtxMenu();
  openPanel('incidents');
  map.doubleClickZoom.disable();
  map.getCanvas().style.cursor = 'crosshair';
  document.getElementById('drawbar').classList.add('open');
  updateDraft();
}

function cancelDraw() {
  drawing = false;
  draft = [];
  map.doubleClickZoom.enable();
  map.getCanvas().style.cursor = '';
  document.getElementById('drawbar').classList.remove('open');
  map.getSource('draft').setData(EMPTY_FC);
}

function updateDraft() {
  const feats = draft.map(function (c, i) {
    return { type: 'Feature', properties: { i: i }, geometry: { type: 'Point', coordinates: c } };
  });
  if (draft.length >= 3) {
    feats.push({ type: 'Feature', properties: {},
      geometry: { type: 'Polygon', coordinates: [draft.concat([draft[0]])] } });
  } else if (draft.length === 2) {
    feats.push({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: draft } });
  }
  map.getSource('draft').setData({ type: 'FeatureCollection', features: feats });
  document.getElementById('draw-count').textContent =
    draft.length + (draft.length === 1 ? ' point' : ' points');
}

function finishDraw() {
  if (draft.length < 3) { alert('A polygon needs at least 3 points.'); return; }
  document.getElementById('inc-desc').value = '';
  document.getElementById('inc-type').value = 'ROAD_CLOSURE';
  document.getElementById('modal').classList.add('open');
}

function cancelModal() {
  document.getElementById('modal').classList.remove('open');
  cancelDraw();
}

async function saveIncident() {
  const body = {
    type: document.getElementById('inc-type').value,
    description: document.getElementById('inc-desc').value.trim(),
    coordinates: draft.slice()          // backend closes the ring
  };
  const resp = await fetch('/incidents', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
  });
  if (!resp.ok) { alert('Failed to save: ' + (await resp.text())); return; }
  document.getElementById('modal').classList.remove('open');
  cancelDraw();
  await loadIncidents();
  scheduleRoute(0);                     // new closure may change the active route
}

// ---- map click: only draws incident vertices ----------------------------
// Routing points are placed via right-click, so a plain click never moves A/B —
// that is what made clicking an incident jump the destination.
map.on('click', function (e) {
  if (drawing) {
    draft.push([e.lngLat.lng, e.lngLat.lat]);
    updateDraft();
  }
});

map.on('dblclick', function (e) {
  if (drawing) { e.preventDefault(); finishDraw(); }
});

document.addEventListener('keydown', function (e) {
  if (!drawing) return;
  if (e.key === 'Escape') cancelDraw();
  if (e.key === 'Enter') finishDraw();
});

// ---- incidents ----------------------------------------------------------
let INCIDENTS = [];

async function loadIncidents() {
  try {
    INCIDENTS = await (await fetch('/incidents')).json();
  } catch (e) {
    INCIDENTS = [];
  }
  setIncidentSourceData();
  renderIncidentList();
}

function setIncidentSourceData() {
  const src = map.getSource('incidents');
  if (!src) return;
  src.setData({
    type: 'FeatureCollection',
    features: INCIDENTS.map(function (inc) {
      const ring = inc.coordinates.slice();
      const a = ring[0], b = ring[ring.length - 1];
      if (a[0] !== b[0] || a[1] !== b[1]) ring.push([a[0], a[1]]);
      return {
        type: 'Feature',
        properties: { id: inc.id, type: inc.type, description: inc.description || '', active: !!inc.active },
        geometry: { type: 'Polygon', coordinates: [ring] }
      };
    })
  });
}

function renderIncidentList() {
  const list = INCIDENTS.slice().sort(function (a, b) { return b.updated_at - a.updated_at; });
  document.getElementById('count').textContent = list.filter(function (i) { return i.active; }).length;
  const el = document.getElementById('incident-list');
  if (!list.length) { el.innerHTML = '<div class="empty">No incidents recorded.</div>'; return; }
  el.innerHTML = list.map(function (inc) {
    const color = inc.active ? (INC_COLORS[inc.type] || INC_COLORS.OTHER) : '#95a5a6';
    return '<div class="incident">' +
      '<div class="row"><span class="dot" style="background:' + color + '"></span>' +
      '<span class="type">' + esc(inc.type) + '</span>' +
      '<span class="active-badge ' + (inc.active ? '' : 'inactive') + '">' +
        (inc.active ? 'ACTIVE' : 'inactive') + '</span></div>' +
      '<div class="desc">' + esc(inc.description || '') + '</div>' +
      '<div class="actions">' +
        '<button onclick="focusIncident(\'' + inc.id + '\')">Show</button>' +
        '<button onclick="toggleIncident(\'' + inc.id + '\',' + (!inc.active) + ')">' +
          (inc.active ? 'Deactivate' : 'Activate') + '</button>' +
        '<button class="danger" onclick="deleteIncident(\'' + inc.id + '\')">Delete</button>' +
      '</div>' +
    '</div>';
  }).join('');
}

const INC_COLORS = {
  ROAD_CLOSURE: '#d63031', ACCIDENT: '#e17055', CONSTRUCTION: '#f9ca24',
  HAZARD: '#6c5ce7', OTHER: '#636e72'
};

function focusIncident(id) {
  const inc = INCIDENTS.find(function (x) { return x.id === id; });
  if (!inc) return;
  const lons = inc.coordinates.map(function (c) { return c[0]; });
  const lats = inc.coordinates.map(function (c) { return c[1]; });
  map.fitBounds([[Math.min.apply(null, lons), Math.min.apply(null, lats)],
                 [Math.max.apply(null, lons), Math.max.apply(null, lats)]],
                { padding: 90, duration: 600 });
}

async function toggleIncident(id, active) {
  const resp = await fetch('/incidents/' + id, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ active: active })
  });
  if (resp.ok) { await loadIncidents(); scheduleRoute(0); }
}

async function deleteIncident(id) {
  if (!confirm('Delete this incident?')) return;
  const resp = await fetch('/incidents/' + id, { method: 'DELETE' });
  if (resp.ok) { await loadIncidents(); scheduleRoute(0); }
}

// popup on incident click
map.on('click', 'incidents-fill', function (e) {
  if (drawing) return;
  const p = e.features[0].properties;
  new maplibregl.Popup({ closeButton: true })
    .setLngLat(e.lngLat)
    .setHTML('<b>' + esc(p.type) + '</b> — ' + esc(p.description || '') + '<br>' +
      '<small>' + (String(p.active) === 'true' ? 'ACTIVE' : 'inactive') + '</small><br>' +
      '<button onclick="toggleIncident(\'' + p.id + '\',' + !(String(p.active) === 'true') + ')">' +
        (String(p.active) === 'true' ? 'Deactivate' : 'Activate') + '</button> ' +
      '<button onclick="deleteIncident(\'' + p.id + '\')">Delete</button>')
    .addTo(map);
});
map.on('mouseenter', 'incidents-fill', function () {
  if (!drawing) map.getCanvas().style.cursor = 'pointer';
});
map.on('mouseleave', 'incidents-fill', function () {
  if (!drawing) map.getCanvas().style.cursor = '';
});



