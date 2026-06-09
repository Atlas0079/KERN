const state = {
	frames: [],
	stableIndex: -1,
	archive: {
		enabled: false,
		loading: false,
		manifest: null,
	},
	selectedEntityId: "",
	selectedLocationId: "",
	selectedPathKey: "",
	locationEntityFilter: "",
	locationEntitiesOpen: false,
	locationNodeHalfById: {},
	layoutCacheByKey: {},
	activeLayoutKey: "",
	activeLayout: null,
	dragging: null,
	dragEdgeRedrawRaf: 0,
	activeScale: 1,
	viewport: {
		x: 0,
		y: 0,
		scale: 1,
		panning: null,
	},
	collapsedPanels: {
		logs: false,
		details: false,
	},
	playback: {
		mode: "idle",
		playingIndex: -1,
		visualEvents: [],
		visualEventIndex: 0,
		overlay: createEmptyOverlay(),
		visibleLogRows: [],
		timerId: 0,
	},
	logFilter: {
		menuOpen: false,
		showInteraction: true,
		showEvent: true,
		keyword: "",
		availableEventTypes: [],
		selectedEventTypes: {},
	},
	nodeImages: { locations: {}, agents: {} },
	imagePickerTarget: null,
};

const GRAPH_WIDTH = 6000;
const GRAPH_HEIGHT = 6000;
const NODE_HALF = 95;
const NODE_MIN_SIZE = 170;
const NODE_BASE_SIZE = 190;
const NODE_MAX_SIZE = 280;
const LAYOUT_STORAGE_KEY = "checkpoint_viewer_layouts_v2";
const NODE_IMAGE_STORAGE_KEY = "checkpoint_viewer_node_images_v1";
const LOCATION_IMAGE_MAX_EDGE = 768;
const AGENT_IMAGE_MAX_EDGE = 384;
const IMAGE_EXPORT_QUALITY = 0.82;
const PLAYBACK_HIGHLIGHT_MS = 280;
const PLAYBACK_SPEECH_MS = 1250;
const PLAYBACK_TRAVEL_MS = 980;
const PLAYBACK_LOG_APPEND_MS = 120;

const fileInput = document.getElementById("fileInput");
const archiveConnectBtn = document.getElementById("archiveConnectBtn");
const sourceHint = document.getElementById("sourceHint");
const panelToggles = Array.from(document.querySelectorAll("[data-collapse-target]"));
const tickList = document.getElementById("tickList");
const tickSlider = document.getElementById("tickSlider");
const tickLabel = document.getElementById("tickLabel");
const prevTickBtn = document.getElementById("prevTickBtn");
const playPauseBtn = document.getElementById("playPauseBtn");
const nextTickBtn = document.getElementById("nextTickBtn");
const worldGrid = document.getElementById("worldGrid");
const detailsPane = document.getElementById("detailsPane");
const logList = document.getElementById("logList");
const worldTitle = document.getElementById("worldTitle");
const logFilterBtn = document.getElementById("logFilterBtn");
const logFilterMenu = document.getElementById("logFilterMenu");
const logFilterInteraction = document.getElementById("logFilterInteraction");
const logFilterEvent = document.getElementById("logFilterEvent");
const logFilterEventTypes = document.getElementById("logFilterEventTypes");
const logFilterKeyword = document.getElementById("logFilterKeyword");
const logFilterClearBtn = document.getElementById("logFilterClearBtn");
const imagePickerInput = document.getElementById("imagePickerInput");
state.nodeImages = loadNodeImageStore();

window.addEventListener("resize", () => {
	if (state.frames.length) {
		renderWorld();
	}
});

for (const toggle of panelToggles) {
	toggle.addEventListener("click", () => {
		const target = String(toggle.dataset.collapseTarget || "");
		if (!target || !(target in state.collapsedPanels)) {
			return;
		}
		state.collapsedPanels[target] = !state.collapsedPanels[target];
		syncPanelChrome();
	});
}

archiveConnectBtn?.addEventListener("click", () => {
	loadArchiveFromServer({ explicit: true });
});

fileInput.addEventListener("change", async (event) => {
	const files = Array.from(event.target.files || []);
	if (!files.length) {
		return;
	}
	const checkpointFiles = files.filter((file) => isCheckpointFileCandidate(file));
	const frames = [];
	for (const file of checkpointFiles) {
		try {
			const text = await file.text();
			const json = JSON.parse(text);
			const tick = Number(json?.meta?.tick ?? -1);
			if (!Number.isFinite(tick) || tick < 0) {
				continue;
			}
			frames.push({
				fileName: file.name,
				tick,
				timeStr: String(json?.meta?.time_str || ""),
				runId: String(json?.meta?.run_id || ""),
				logScope: String(json?.meta?.log_scope || ""),
				world: json?.world || {},
				log: Array.isArray(json?.log) ? json.log : [],
			});
		} catch (error) {
			console.error("failed to parse", file.name, error);
		}
	}
	frames.sort((a, b) => a.tick - b.tick);
	stopPlayback({ syncLogs: false });
	state.archive.enabled = false;
	state.archive.loading = false;
	state.archive.manifest = null;
	state.frames = frames;
	state.stableIndex = frames.length ? 0 : -1;
	state.selectedEntityId = "";
	state.selectedLocationId = "";
	rebuildLogFilterMetadata(frames);
	syncVisibleLogRowsToStable();
	render();
	setSourceHint(`已加载 JSON checkpoint 目录：${frames.length} ticks`);
});

detailsPane.addEventListener("click", (event) => {
	const rawTarget = event.target;
	if (!(rawTarget instanceof Element)) {
		return;
	}
	const target = rawTarget.closest("[data-action]");
	if (!(target instanceof HTMLElement)) {
		return;
	}
	const action = String(target.dataset.action || "");
	if (!action) {
		return;
	}
	const kind = String(target.dataset.kind || "");
	const id = String(target.dataset.id || "");
	if (action === "select-entity") {
		if (!id) {
			return;
		}
		state.selectedEntityId = id;
		state.selectedLocationId = findLocationIdForEntity(getDisplayedFrame(), id) || state.selectedLocationId;
		renderDetails();
		renderWorld();
		return;
	}
	if (action === "toggle-location-entities") {
		state.locationEntitiesOpen = !state.locationEntitiesOpen;
		renderDetails();
		return;
	}
	if (!kind || !id) {
		return;
	}
	if (action === "set-image") {
		state.imagePickerTarget = { kind, id };
		imagePickerInput.value = "";
		imagePickerInput.click();
		return;
	}
	if (action === "clear-image") {
		clearNodeImage(kind, id);
		renderWorld();
		renderDetails();
	}
});

detailsPane.addEventListener("input", (event) => {
	const target = event.target;
	if (!(target instanceof HTMLInputElement)) {
		return;
	}
	if (target.id === "locationEntityFilter") {
		const selectionStart = Number(target.selectionStart ?? target.value.length);
		state.locationEntityFilter = String(target.value || "");
		renderDetails();
		const nextInput = document.getElementById("locationEntityFilter");
		if (nextInput instanceof HTMLInputElement) {
			nextInput.focus();
			const cursor = Math.min(selectionStart, nextInput.value.length);
			nextInput.setSelectionRange(cursor, cursor);
		}
	}
});

imagePickerInput.addEventListener("change", async (event) => {
	const file = Array.from(event.target.files || [])[0];
	const target = state.imagePickerTarget;
	state.imagePickerTarget = null;
	if (!file || !target) {
		return;
	}
	const maxEdge = target.kind === "location" ? LOCATION_IMAGE_MAX_EDGE : AGENT_IMAGE_MAX_EDGE;
	const dataUrl = await readFileAsDataUrl(file, maxEdge);
	if (!dataUrl) {
		return;
	}
	setNodeImage(target.kind, target.id, dataUrl);
	renderWorld();
	renderDetails();
});

tickSlider.addEventListener("input", () => {
	const index = Number(tickSlider.value || 0);
	setStableFrameIndex(index);
});

prevTickBtn.addEventListener("click", () => {
	setStableFrameIndex(getActiveTimelineIndex() - 1);
});

nextTickBtn.addEventListener("click", () => {
	setStableFrameIndex(getActiveTimelineIndex() + 1);
});

playPauseBtn.addEventListener("click", () => {
	togglePlayback();
});

logFilterBtn.addEventListener("click", () => {
	state.logFilter.menuOpen = !state.logFilter.menuOpen;
	syncLogFilterUi();
});

logFilterInteraction.addEventListener("change", () => {
	state.logFilter.showInteraction = !!logFilterInteraction.checked;
	renderLog();
});

logFilterEvent.addEventListener("change", () => {
	state.logFilter.showEvent = !!logFilterEvent.checked;
	renderLog();
});

logFilterEventTypes.addEventListener("change", (event) => {
	const target = event.target;
	if (!(target instanceof HTMLInputElement)) {
		return;
	}
	const eventType = String(target.dataset.eventType || "");
	if (!eventType) {
		return;
	}
	state.logFilter.selectedEventTypes[eventType] = !!target.checked;
	renderLog();
});

logFilterKeyword.addEventListener("input", () => {
	state.logFilter.keyword = String(logFilterKeyword.value || "");
	renderLog();
});

logFilterClearBtn.addEventListener("click", () => {
	state.logFilter.showInteraction = true;
	state.logFilter.showEvent = true;
	state.logFilter.keyword = "";
	for (const eventType of state.logFilter.availableEventTypes) {
		state.logFilter.selectedEventTypes[eventType.name] = true;
	}
	syncLogFilterUi();
	renderLog();
});

document.addEventListener("pointerdown", (event) => {
	if (!state.logFilter.menuOpen) {
		return;
	}
	const target = event.target;
	if (target instanceof Element && (target.closest("#logFilterMenu") || target.closest("#logFilterBtn"))) {
		return;
	}
	state.logFilter.menuOpen = false;
	syncLogFilterUi();
});

document.addEventListener("DOMContentLoaded", () => {
	syncPanelChrome();
	loadArchiveFromServer({ explicit: false });
});

function createEmptyOverlay() {
	return {
		activeActorId: "",
		bubble: null,
		travel: null,
	};
}

function isCheckpointFileCandidate(file) {
	const name = String(file?.name || "").toLowerCase();
	return name.endsWith(".json");
}

async function loadArchiveFromServer(options = {}) {
	const explicit = options.explicit === true;
	if (state.archive.loading) {
		return;
	}
	state.archive.loading = true;
	setSourceHint("正在连接本地 archive 服务...");
	try {
		const response = await fetch("./api/manifest", { cache: "no-store" });
		if (!response.ok) {
			throw new Error(`HTTP ${response.status}`);
		}
		const manifest = await response.json();
		const ticks = Array.isArray(manifest?.ticks) ? manifest.ticks.map((x) => Number(x)).filter((x) => Number.isFinite(x) && x >= 0) : [];
		if (!ticks.length) {
			throw new Error("manifest has no ticks");
		}
		stopPlayback({ syncLogs: false });
		state.archive.enabled = true;
		state.archive.manifest = manifest;
		state.frames = ticks.map((tick) => createLazyArchiveFrame(tick, manifest));
		state.stableIndex = 0;
		state.selectedEntityId = "";
		state.selectedLocationId = "";
		state.selectedPathKey = "";
		rebuildLogFilterMetadata([]);
		await ensureFrameLoaded(0);
		syncVisibleLogRowsToStable();
		rebuildLogFilterMetadata(state.frames.filter((frame) => !frame.lazy));
		render();
		setSourceHint(`Archive 已连接：${manifest.archive_dir || manifest.run_id || "local"} · ${ticks.length} ticks`);
	} catch (error) {
		state.archive.enabled = false;
		if (explicit) {
			setSourceHint(`连接 Archive 失败：${error?.message || error}`);
		} else {
			setSourceHint("通过 checkpoint_viewer_server.py 读取 run archive；仍支持旧 JSON 目录导入");
		}
	} finally {
		state.archive.loading = false;
	}
}

function createLazyArchiveFrame(tick, manifest) {
	return {
		fileName: `archive:${tick}`,
		tick,
		timeStr: "",
		runId: String(manifest?.run_id || ""),
		logScope: "tick",
		world: {},
		log: [],
		lazy: true,
		loading: false,
		error: "",
	};
}

async function ensureFrameLoaded(index) {
	const frame = getFrameByIndex(index);
	if (!frame || !frame.lazy || frame.loading) {
		return frame;
	}
	frame.loading = true;
	frame.error = "";
	try {
		const response = await fetch(`./api/tick/${encodeURIComponent(String(frame.tick))}`, { cache: "no-store" });
		if (!response.ok) {
			throw new Error(`HTTP ${response.status}`);
		}
		const payload = await response.json();
		Object.assign(frame, {
			fileName: String(payload?.fileName || frame.fileName || `archive:${frame.tick}`),
			tick: Number(payload?.tick ?? frame.tick),
			timeStr: String(payload?.timeStr || ""),
			runId: String(payload?.runId || frame.runId || ""),
			logScope: String(payload?.logScope || "tick"),
			world: payload?.world || {},
			log: Array.isArray(payload?.log) ? payload.log : [],
			lazy: false,
			loading: false,
			error: "",
		});
		rebuildLogFilterMetadata(state.frames.filter((item) => !item.lazy));
		return frame;
	} catch (error) {
		frame.loading = false;
		frame.error = String(error?.message || error || "load failed");
		throw error;
	}
}

async function ensurePlaybackFramesLoaded(targetIndex) {
	await ensureFrameLoaded(Math.max(0, targetIndex - 1));
	await ensureFrameLoaded(targetIndex);
}

function setSourceHint(text) {
	if (sourceHint) {
		sourceHint.textContent = String(text || "");
	}
}

function syncPanelChrome() {
	document.body.classList.toggle("logs-collapsed", state.collapsedPanels.logs);
	document.body.classList.toggle("details-collapsed", state.collapsedPanels.details);
	const labels = {
		logs: state.collapsedPanels.logs ? "›" : "‹",
		details: state.collapsedPanels.details ? "‹" : "›",
	};
	for (const toggle of panelToggles) {
		const target = String(toggle.dataset.collapseTarget || "");
		if (labels[target]) {
			toggle.textContent = labels[target];
		}
	}
}

function graphTransformStyle() {
	const x = Number(state.viewport.x) || 0;
	const y = Number(state.viewport.y) || 0;
	const scale = Math.max(0.35, Math.min(2.4, Number(state.viewport.scale) || 1));
	state.viewport.scale = scale;
	state.activeScale = scale;
	return `translate(calc(-50% + ${x}px), calc(-50% + ${y}px)) scale(${scale})`;
}

function loadNodeImageStore() {
	try {
		const raw = localStorage.getItem(NODE_IMAGE_STORAGE_KEY);
		if (!raw) {
			return { locations: {}, agents: {} };
		}
		const parsed = JSON.parse(raw);
		const locations = parsed && typeof parsed === "object" && parsed.locations && typeof parsed.locations === "object" ? parsed.locations : {};
		const agents = parsed && typeof parsed === "object" && parsed.agents && typeof parsed.agents === "object" ? parsed.agents : {};
		return { locations, agents };
	} catch (_error) {
		return { locations: {}, agents: {} };
	}
}

function persistNodeImageStore() {
	try {
		localStorage.setItem(NODE_IMAGE_STORAGE_KEY, JSON.stringify(state.nodeImages || { locations: {}, agents: {} }));
	} catch (_error) {
	}
}

function getNodeImage(kind, id) {
	const safeId = String(id || "");
	if (!safeId) {
		return "";
	}
	if (kind === "location") {
		return String(state.nodeImages?.locations?.[safeId] || "");
	}
	if (kind === "agent") {
		return String(state.nodeImages?.agents?.[safeId] || "");
	}
	return "";
}

function setNodeImage(kind, id, dataUrl) {
	const safeId = String(id || "");
	const safeDataUrl = String(dataUrl || "");
	if (!safeId || !safeDataUrl) {
		return;
	}
	if (kind === "location") {
		state.nodeImages.locations[safeId] = safeDataUrl;
	} else if (kind === "agent") {
		state.nodeImages.agents[safeId] = safeDataUrl;
	}
	persistNodeImageStore();
}

function clearNodeImage(kind, id) {
	const safeId = String(id || "");
	if (!safeId) {
		return;
	}
	if (kind === "location") {
		delete state.nodeImages.locations[safeId];
	} else if (kind === "agent") {
		delete state.nodeImages.agents[safeId];
	}
	persistNodeImageStore();
}

async function readFileAsDataUrl(file, maxEdge) {
	const safeMaxEdge = Math.max(64, Number(maxEdge) || 256);
	const image = await readFileAsImageElement(file);
	if (!image) {
		return "";
	}
	const width = Math.max(1, Number(image.naturalWidth) || Number(image.width) || 1);
	const height = Math.max(1, Number(image.naturalHeight) || Number(image.height) || 1);
	const scale = Math.min(1, safeMaxEdge / Math.max(width, height));
	const targetWidth = Math.max(1, Math.round(width * scale));
	const targetHeight = Math.max(1, Math.round(height * scale));
	const canvas = document.createElement("canvas");
	canvas.width = targetWidth;
	canvas.height = targetHeight;
	const context = canvas.getContext("2d");
	if (!context) {
		return "";
	}
	context.drawImage(image, 0, 0, targetWidth, targetHeight);
	const exported = canvas.toDataURL("image/jpeg", IMAGE_EXPORT_QUALITY);
	if (typeof exported === "string" && exported.length > 16) {
		return exported;
	}
	return await new Promise((resolve) => {
		const reader = new FileReader();
		reader.onload = () => resolve(String(reader.result || ""));
		reader.onerror = () => resolve("");
		reader.readAsDataURL(file);
	});
}

async function readFileAsImageElement(file) {
	const dataUrl = await new Promise((resolve) => {
		const reader = new FileReader();
		reader.onload = () => resolve(String(reader.result || ""));
		reader.onerror = () => resolve("");
		reader.readAsDataURL(file);
	});
	if (!dataUrl) {
		return null;
	}
	return await new Promise((resolve) => {
		const image = new Image();
		image.onload = () => resolve(image);
		image.onerror = () => resolve(null);
		image.src = dataUrl;
	});
}

function clearPlaybackTimer() {
	if (state.playback.timerId) {
		window.clearTimeout(state.playback.timerId);
		state.playback.timerId = 0;
	}
}

function stopPlayback(options = {}) {
	const syncLogs = options.syncLogs !== false;
	clearPlaybackTimer();
	state.playback.mode = "idle";
	state.playback.playingIndex = -1;
	state.playback.visualEvents = [];
	state.playback.visualEventIndex = 0;
	state.playback.overlay = createEmptyOverlay();
	if (syncLogs) {
		syncVisibleLogRowsToStable();
	}
}

function pausePlayback() {
	if (state.playback.mode !== "playing") {
		return;
	}
	clearPlaybackTimer();
	state.playback.mode = "paused";
	render();
}

function resumePlayback() {
	if (state.playback.mode !== "paused") {
		return;
	}
	state.playback.mode = "playing";
	render();
	scheduleNextPlaybackStep(120);
}

function togglePlayback() {
	if (!state.frames.length) {
		return;
	}
	if (state.playback.mode === "playing") {
		pausePlayback();
		return;
	}
	if (state.playback.mode === "paused") {
		resumePlayback();
		return;
	}
	startPlaybackFromStable();
}

async function startPlaybackFromStable() {
	if (!state.frames.length) {
		return;
	}
	const nextIndex = state.stableIndex + 1;
	if (nextIndex < 0 || nextIndex >= state.frames.length) {
		return;
	}
	try {
		await ensurePlaybackFramesLoaded(nextIndex);
	} catch (error) {
		setSourceHint(`加载播放帧失败：${error?.message || error}`);
		render();
		return;
	}
	const segment = buildPlaybackSegment(nextIndex);
	state.playback.mode = "playing";
	state.playback.playingIndex = nextIndex;
	state.playback.visualEvents = compileVisualEvents(segment);
	state.playback.visualEventIndex = 0;
	state.playback.overlay = createEmptyOverlay();
	state.playback.visibleLogRows = [];
	render();
	if (!state.playback.visualEvents.length) {
		finishSegmentPlayback();
		return;
	}
	scheduleNextPlaybackStep(80);
}

function scheduleNextPlaybackStep(delayMs) {
	clearPlaybackTimer();
	state.playback.timerId = window.setTimeout(() => {
		state.playback.timerId = 0;
		if (state.playback.mode !== "playing") {
			return;
		}
		stepPlayback();
	}, Math.max(0, Number(delayMs) || 0));
}

function stepPlayback() {
	if (state.playback.mode !== "playing") {
		return;
	}
	if (state.playback.visualEventIndex >= state.playback.visualEvents.length) {
		finishSegmentPlayback();
		return;
	}
	const visualEvent = state.playback.visualEvents[state.playback.visualEventIndex];
	state.playback.visualEventIndex += 1;
	applyVisualEvent(visualEvent);
	render();
	scheduleNextPlaybackStep(Number(visualEvent?.durationMs) || PLAYBACK_LOG_APPEND_MS);
}

function finishSegmentPlayback() {
	if (state.playback.playingIndex >= 0) {
		state.stableIndex = state.playback.playingIndex;
	}
	stopPlayback({ syncLogs: true });
	render();
}

async function setStableFrameIndex(index) {
	if (!state.frames.length) {
		return;
	}
	const clamped = Math.max(0, Math.min(state.frames.length - 1, Number(index) || 0));
	stopPlayback({ syncLogs: false });
	state.stableIndex = clamped;
	state.selectedEntityId = "";
	state.selectedLocationId = "";
	state.selectedPathKey = "";
	render();
	try {
		await ensureFrameLoaded(clamped);
	} catch (error) {
		setSourceHint(`加载 tick ${state.frames[clamped]?.tick ?? clamped} 失败：${error?.message || error}`);
	}
	syncVisibleLogRowsToStable();
	render();
}

function syncVisibleLogRowsToStable() {
	const frame = getStableFrame();
	state.playback.visibleLogRows = Array.isArray(frame?.log) ? [...frame.log] : [];
}

function render() {
	renderTickList();
	renderWorld();
	renderDetails();
	renderLog();
}

function syncLogFilterUi() {
	logFilterMenu.hidden = !state.logFilter.menuOpen;
	logFilterBtn.classList.toggle("open", state.logFilter.menuOpen);
	logFilterInteraction.checked = !!state.logFilter.showInteraction;
	logFilterEvent.checked = !!state.logFilter.showEvent;
	logFilterKeyword.value = String(state.logFilter.keyword || "");
	renderLogEventTypeFilterOptions();
}

function rebuildLogFilterMetadata(frames) {
	const counts = new Map();
	for (const frame of Array.isArray(frames) ? frames : []) {
		for (const row of Array.isArray(frame?.log) ? frame.log : []) {
			const eventType = getRowEventType(row);
			if (!eventType) {
				continue;
			}
			counts.set(eventType, (counts.get(eventType) || 0) + 1);
		}
	}
	const nextTypes = Array.from(counts.entries())
		.map(([name, count]) => ({ name, count }))
		.sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
	const nextSelected = {};
	for (const item of nextTypes) {
		if (Object.prototype.hasOwnProperty.call(state.logFilter.selectedEventTypes, item.name)) {
			nextSelected[item.name] = !!state.logFilter.selectedEventTypes[item.name];
		} else {
			nextSelected[item.name] = true;
		}
	}
	state.logFilter.availableEventTypes = nextTypes;
	state.logFilter.selectedEventTypes = nextSelected;
}

function renderLogEventTypeFilterOptions() {
	const types = Array.isArray(state.logFilter.availableEventTypes) ? state.logFilter.availableEventTypes : [];
	if (!types.length) {
		logFilterEventTypes.className = "event-type-empty";
		logFilterEventTypes.textContent = "当前数据没有 event.type";
		return;
	}
	logFilterEventTypes.className = "event-type-list";
	logFilterEventTypes.innerHTML = types.map((item) => {
		const checked = state.logFilter.selectedEventTypes[item.name] !== false;
		return `
			<label class="event-type-item">
				<span class="left">
					<input type="checkbox" data-event-type="${escapeHtml(item.name)}" ${checked ? "checked" : ""}>
					<span class="event-name" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</span>
				</span>
				<span class="event-count">${item.count}</span>
			</label>
		`;
	}).join("");
}

function getRowEventType(row) {
	if (!row || typeof row !== "object") {
		return "";
	}
	if (String(row.kind || "") !== "event") {
		return "";
	}
	const raw = row?.event?.type;
	const text = String(raw || "").trim();
	return text || "UnknownEvent";
}

function getFrameByIndex(index) {
	if (index < 0 || index >= state.frames.length) {
		return null;
	}
	return state.frames[index];
}

function getStableFrame() {
	return getFrameByIndex(state.stableIndex);
}

function getDisplayedFrame() {
	if (state.playback.playingIndex > 0) {
		return getFrameByIndex(state.playback.playingIndex - 1);
	}
	if (state.playback.playingIndex === 0) {
		return getFrameByIndex(0);
	}
	return getStableFrame();
}

function getPlaybackTargetFrame() {
	if (state.playback.playingIndex < 0) {
		return null;
	}
	return getFrameByIndex(state.playback.playingIndex);
}

function getActiveTimelineIndex() {
	if (state.playback.playingIndex >= 0) {
		return state.playback.playingIndex;
	}
	return state.stableIndex;
}

function buildPlaybackSegment(targetIndex) {
	return {
		fromFrame: getFrameByIndex(Math.max(0, targetIndex - 1)),
		toFrame: getFrameByIndex(targetIndex),
		logRows: normalizeLogRows(getFrameByIndex(targetIndex)?.log || []),
	};
}

function normalizeLogRows(rows) {
	return [...rows].sort((a, b) => {
		const tickA = Number(a?.tick ?? 0);
		const tickB = Number(b?.tick ?? 0);
		if (tickA !== tickB) {
			return tickA - tickB;
		}
		const seqA = Number(a?.seq ?? 0);
		const seqB = Number(b?.seq ?? 0);
		if (seqA !== seqB) {
			return seqA - seqB;
		}
		return String(a?.kind || "").localeCompare(String(b?.kind || ""));
	});
}

function compileVisualEvents(segment) {
	const visualEvents = [];
	for (const row of segment.logRows) {
		visualEvents.push(...compileLogRowToVisualEvents(row));
	}
	return visualEvents;
}

function compileLogRowToVisualEvents(row) {
	if (!row || typeof row !== "object") {
		return [];
	}
	if (row.kind === "interaction") {
		return compileInteractionRow(row);
	}
	if (row.kind === "event") {
		return compileEventRow(row);
	}
	return [
		{ type: "log-append", row, durationMs: PLAYBACK_LOG_APPEND_MS },
	];
}

function compileInteractionRow(row) {
	const actorId = String(row.actor_id || "");
	const verb = String(row.verb || "");
	const speech = String(row.speech || "");
	const status = String(row.status || "");
	if (speech) {
		return [
			{ type: "highlight", actorId, durationMs: PLAYBACK_HIGHLIGHT_MS },
			{ type: "speech", actorId, speakerName: String(row.actor_name || actorId || "Unknown"), text: speech, durationMs: PLAYBACK_SPEECH_MS },
			{ type: "log-append", row, durationMs: PLAYBACK_LOG_APPEND_MS },
		];
	}
	if (verb === "Travel" && status === "success" && String(row.travel_phase || "") === "depart") {
		return [
			{ type: "highlight", actorId, durationMs: PLAYBACK_HIGHLIGHT_MS },
			{
				type: "travel",
				actorId,
				actorName: String(row.actor_name || actorId || "Unknown"),
				fromLocationId: String(row.source_location_id || ""),
				toLocationId: String(row.to_location_id || ""),
				durationMs: PLAYBACK_TRAVEL_MS,
			},
			{ type: "log-append", row, durationMs: PLAYBACK_LOG_APPEND_MS },
		];
	}
	return [
		{ type: "highlight", actorId, durationMs: PLAYBACK_HIGHLIGHT_MS },
		{ type: "log-append", row, durationMs: PLAYBACK_LOG_APPEND_MS },
	];
}

function compileEventRow(row) {
	const event = row.event || {};
	const eventType = String(event.type || "");
	if (eventType === "ConversationSpoken") {
		return [
			{ type: "highlight", actorId: String(event.speaker_id || row.actor_id || ""), durationMs: PLAYBACK_HIGHLIGHT_MS },
			{
				type: "speech",
				actorId: String(event.speaker_id || row.actor_id || ""),
				speakerName: resolveEventSpeakerName(event, row),
				text: String(event.text || ""),
				durationMs: PLAYBACK_SPEECH_MS,
			},
			{ type: "log-append", row, durationMs: PLAYBACK_LOG_APPEND_MS },
		];
	}
	const actorId = String(row.actor_id || event.speaker_id || event.entity_id || "");
	if (eventType.startsWith("Task") || eventType.startsWith("Entity") || eventType.startsWith("Conversation")) {
		return [
			{ type: "highlight", actorId, durationMs: PLAYBACK_HIGHLIGHT_MS },
			{ type: "log-append", row, durationMs: PLAYBACK_LOG_APPEND_MS },
		];
	}
	return [{ type: "log-append", row, durationMs: PLAYBACK_LOG_APPEND_MS }];
}

function resolveEventSpeakerName(event, row) {
	const speakerId = String(event.speaker_id || row.actor_id || "");
	const displayedFrame = getDisplayedFrame();
	const entityMap = buildEntityMap(displayedFrame);
	const entity = entityMap.get(speakerId);
	return entityDisplayName(entity, entity) || speakerId || "Unknown";
}

function applyVisualEvent(visualEvent) {
	state.playback.overlay = createEmptyOverlay();
	if (!visualEvent || typeof visualEvent !== "object") {
		return;
	}
	if (visualEvent.type === "log-append") {
		state.playback.visibleLogRows = [...state.playback.visibleLogRows, visualEvent.row];
		return;
	}
	if (visualEvent.type === "highlight") {
		state.playback.overlay = {
			activeActorId: String(visualEvent.actorId || ""),
			bubble: null,
			travel: null,
		};
		return;
	}
	if (visualEvent.type === "speech") {
		state.playback.overlay = {
			activeActorId: String(visualEvent.actorId || ""),
			bubble: {
				actorId: String(visualEvent.actorId || ""),
				speakerName: String(visualEvent.speakerName || ""),
				text: String(visualEvent.text || ""),
			},
			travel: null,
		};
		return;
	}
	if (visualEvent.type === "travel") {
		state.playback.overlay = {
			activeActorId: String(visualEvent.actorId || ""),
			bubble: null,
			travel: {
				actorId: String(visualEvent.actorId || ""),
				actorName: String(visualEvent.actorName || ""),
				fromLocationId: String(visualEvent.fromLocationId || ""),
				toLocationId: String(visualEvent.toLocationId || ""),
				durationMs: Number(visualEvent.durationMs) || PLAYBACK_TRAVEL_MS,
			},
		};
	}
}

function renderTickList() {
	tickList.innerHTML = "";
	if (!state.frames.length) {
		tickList.innerHTML = '<div class="empty">还没有加载 checkpoint 文件</div>';
		tickSlider.disabled = true;
		prevTickBtn.disabled = true;
		playPauseBtn.disabled = true;
		nextTickBtn.disabled = true;
		playPauseBtn.textContent = "播放";
		playPauseBtn.classList.remove("paused");
		tickLabel.textContent = "Tick -";
		return;
	}
	tickSlider.disabled = false;
	tickSlider.min = "0";
	tickSlider.max = String(state.frames.length - 1);
	tickSlider.value = String(getActiveTimelineIndex());
	prevTickBtn.disabled = getActiveTimelineIndex() <= 0;
	nextTickBtn.disabled = getActiveTimelineIndex() >= state.frames.length - 1;
	const current = getStableFrame();
	const playbackTarget = getPlaybackTargetFrame();
	const displayed = getDisplayedFrame();
	if (state.playback.mode === "playing" || state.playback.mode === "paused") {
		const total = state.playback.visualEvents.length;
		const done = Math.min(state.playback.visualEventIndex, total);
		tickLabel.textContent = `播放 ${displayed?.tick ?? "-"} → ${playbackTarget?.tick ?? "-"} · ${done}/${total}`;
	} else {
		tickLabel.textContent = `Tick ${current?.tick ?? "-"} / ${current?.timeStr || current?.fileName || "-"}`;
	}
	playPauseBtn.disabled = state.playback.mode === "idle" && state.stableIndex >= state.frames.length - 1;
	playPauseBtn.textContent = state.playback.mode === "playing" ? "暂停" : state.playback.mode === "paused" ? "继续" : "播放";
	playPauseBtn.classList.toggle("paused", state.playback.mode === "paused");
	for (const [index, frame] of state.frames.entries()) {
		const item = document.createElement("button");
		const classes = ["tick-marker"];
		if (index === state.stableIndex && state.playback.mode === "idle") {
			classes.push("active");
		}
		if (index === state.playback.playingIndex) {
			classes.push("active", "playing");
		}
		item.className = classes.join(" ");
		item.textContent = `#${frame.tick}`;
		const logCount = Array.isArray(frame.log) ? frame.log.length : 0;
		item.title = frame.lazy ? `${frame.fileName} | 未加载` : `${frame.timeStr || frame.fileName} | log=${logCount}`;
		item.addEventListener("click", () => setStableFrameIndex(index));
		tickList.appendChild(item);
	}
}

function renderWorld() {
	worldGrid.innerHTML = "";
	state.locationNodeHalfById = {};
	attachCanvasViewportHandlers();
	const frame = getDisplayedFrame();
	const playbackTarget = getPlaybackTargetFrame();
	if (!frame) {
		worldTitle.textContent = "World";
		worldGrid.innerHTML = '<div class="empty">请选择 checkpoint 文件</div>';
		return;
	}
	if (playbackTarget) {
		worldTitle.textContent = `World · 播放 ${frame.tick} → ${playbackTarget.tick} · ${playbackTarget.timeStr || playbackTarget.fileName}`;
	} else {
		worldTitle.textContent = `World · Tick ${frame.tick} · ${frame.timeStr || frame.fileName}`;
	}
	if (frame.lazy || frame.loading) {
		worldGrid.innerHTML = '<div class="empty">正在加载当前 tick...</div>';
		return;
	}
	if (frame.error) {
		worldGrid.innerHTML = `<div class="empty">加载失败：${escapeHtml(frame.error)}</div>`;
		return;
	}
	const locations = Array.isArray(frame.world?.locations) ? frame.world.locations : [];
	const paths = Array.isArray(frame.world?.paths) ? frame.world.paths : [];
	const worldEntities = buildEntityMap(frame);
	if (!locations.length) {
		worldGrid.innerHTML = '<div class="empty">这个 checkpoint 没有 location 数据</div>';
		return;
	}
	const layout = getOrCreateLayout(frame, locations, paths);
	const edgeHtml = buildGraphEdges(paths, layout, state.playback.overlay.travel);
	const nodeHtml = locations.map((loc) => {
		const locationId = String(loc.location_id || "");
		const point = layout.get(locationId) || { x: 600, y: 380 };
		const entities = Array.isArray(loc.entities) ? loc.entities : [];
		const agentEntities = [];
		const otherEntities = [];
		for (const entity of entities) {
			const entityId = String(entity.instance_id || "");
			if (state.playback.overlay.travel && String(state.playback.overlay.travel.actorId || "") === entityId) {
				continue;
			}
			const tags = getEntityTags(worldEntities.get(entityId));
			if (tags.includes("agent")) {
				agentEntities.push(entity);
			} else {
				otherEntities.push(entity);
			}
		}
		const visibleAgents = agentEntities.slice(0, 4);
		const hiddenAgentCount = Math.max(0, agentEntities.length - visibleAgents.length);
		const agentTokens = visibleAgents.map((entity) => {
			const entityId = String(entity.instance_id || "");
			const fullEntity = worldEntities.get(entityId);
			const label = entityDisplayName(entity, fullEntity);
			const agentImage = getNodeImage("agent", entityId);
			const classes = [
				"agent-token",
				agentImage ? "has-image" : "",
				state.selectedEntityId === entityId ? "selected" : "",
				isActorCurrentlyActive(entityId) ? "active" : "",
			].filter(Boolean).join(" ");
			return `<button class="${classes}" data-entity-id="${escapeHtml(entityId)}" title="${escapeHtml(label)}">${agentImage ? `<img class="agent-token-bg" src="${escapeHtml(agentImage)}" alt="${escapeHtml(label)}">` : escapeHtml(getEntityAvatarLabel(label))}</button>`;
		}).join("") + (hiddenAgentCount > 0 ? `<span class="agent-token overflow" title="还有 ${hiddenAgentCount} 个 agent">+${hiddenAgentCount}</span>` : "");
		const locationName = String(loc.location_name || locationId || "Unnamed");
		const locationImage = getNodeImage("location", locationId);
		const nodeSize = computeLocationNodeSize({
			title: locationName,
			agentCount: agentEntities.length,
			otherCount: otherEntities.length,
			totalCount: entities.length,
		});
		state.locationNodeHalfById[locationId] = nodeSize / 2;
		const entitySummary = entities.length
			? `<span class="entity-count-pill">${entities.length} entities</span>`
			: '<span class="empty">无实体</span>';
		return `
			<div
				class="location-node${locationImage ? " has-image" : ""}${state.selectedLocationId === locationId ? " selected" : ""}"
				data-location-id="${escapeHtml(locationId)}"
				style="left:${point.x}px;top:${point.y}px;--node-size:${nodeSize}px;"
			>
				${locationImage ? `<img class="location-node-bg" src="${escapeHtml(locationImage)}" alt="${escapeHtml(locationName)}">` : ""}
				<div class="location-node-header">
					<div class="location-node-title">${escapeHtml(locationName)}</div>
					<div class="location-node-meta">${entities.length} entities</div>
				</div>
				<div class="location-node-body">
					<div class="agent-slots">${agentTokens || '<span class="empty">无 agent</span>'}</div>
					<div class="entity-summary">${entitySummary}</div>
				</div>
			</div>
		`;
	}).join("");
	worldGrid.innerHTML = `
		<div class="graph-viewport">
			<div class="graph-stage" style="transform: ${graphTransformStyle()};">
				<svg class="graph-svg" viewBox="0 0 ${GRAPH_WIDTH} ${GRAPH_HEIGHT}" preserveAspectRatio="xMidYMid meet">
					${edgeHtml}
				</svg>
				<div class="graph-nodes">
					${nodeHtml}
				</div>
				<div class="graph-overlay">
					${buildPlaybackOverlayHtml(frame, layout, worldEntities)}
				</div>
			</div>
		</div>
	`;
	for (const node of worldGrid.querySelectorAll(".location-node")) {
		node.addEventListener("pointerdown", (event) => {
			startNodeDrag(event, node);
		});
		node.addEventListener("click", (event) => {
			if (state.dragging && state.dragging.didMove) {
				return;
			}
			const locationId = node.dataset.locationId || "";
			const targetElement = event.target instanceof Element ? event.target.closest("[data-entity-id]") : null;
			const entityId = targetElement instanceof HTMLElement ? String(targetElement.dataset.entityId || "") : "";
			if (entityId) {
				state.selectedEntityId = entityId;
				state.selectedLocationId = locationId;
				state.selectedPathKey = "";
			} else {
				state.selectedLocationId = locationId;
				state.selectedEntityId = "";
				state.selectedPathKey = "";
			}
			renderDetails();
			renderWorld();
		});
	}
	for (const pathElement of worldGrid.querySelectorAll("[data-path-key]")) {
		pathElement.addEventListener("pointerdown", (event) => {
			event.stopPropagation();
		});
		pathElement.addEventListener("click", (event) => {
			event.preventDefault();
			event.stopPropagation();
			state.selectedPathKey = String(pathElement.dataset.pathKey || "");
			state.selectedEntityId = "";
			state.selectedLocationId = "";
			renderDetails();
			renderWorld();
		});
	}
}

function buildPlaybackOverlayHtml(frame, layout, entityMap) {
	const overlay = state.playback.overlay || createEmptyOverlay();
	const fragments = [];
	if (overlay.travel) {
		const from = layout.get(String(overlay.travel.fromLocationId || ""));
		const to = layout.get(String(overlay.travel.toLocationId || ""));
		if (from && to) {
			const actor = entityMap.get(String(overlay.travel.actorId || ""));
			const actorLabel = entityDisplayName(actor, actor) || String(overlay.travel.actorName || "");
			fragments.push(`
				<div
					class="travel-token"
					title="${escapeHtml(actorLabel)}"
					style="
						left:${from.x}px;
						top:${from.y}px;
						--travel-dx:${to.x - from.x}px;
						--travel-dy:${to.y - from.y}px;
						animation-duration:${Math.max(100, Number(overlay.travel.durationMs) || PLAYBACK_TRAVEL_MS)}ms;
					"
				>${escapeHtml(getEntityAvatarLabel(actorLabel))}</div>
			`);
		}
	}
	if (overlay.bubble) {
		const anchor = resolveActorAnchorPoint(frame, entityMap, String(overlay.bubble.actorId || ""), layout);
		if (anchor) {
			fragments.push(`
				<div class="bubble" style="left:${anchor.x}px; top:${anchor.y - 34}px;">
					<div class="bubble-speaker">${escapeHtml(String(overlay.bubble.speakerName || ""))}</div>
					<div>${escapeHtml(String(overlay.bubble.text || ""))}</div>
				</div>
			`);
		}
	}
	return fragments.join("");
}

function resolveActorAnchorPoint(frame, entityMap, actorId, layout) {
	if (!actorId) {
		return null;
	}
	if (state.playback.overlay.travel && String(state.playback.overlay.travel.actorId || "") === actorId) {
		const from = layout.get(String(state.playback.overlay.travel.fromLocationId || ""));
		const to = layout.get(String(state.playback.overlay.travel.toLocationId || ""));
		if (from && to) {
			return {
				x: (from.x + to.x) / 2,
				y: (from.y + to.y) / 2,
			};
		}
	}
	const locationId = findLocationIdForEntity(frame, actorId);
	if (!locationId) {
		return null;
	}
	const point = layout.get(locationId);
	if (!point) {
		return null;
	}
	const nodeHalf = Number(state.locationNodeHalfById[locationId]) || NODE_HALF;
	return {
		x: point.x,
		y: point.y - nodeHalf - 14,
	};
}

function isActorCurrentlyActive(entityId) {
	return String(state.playback.overlay?.activeActorId || "") === String(entityId || "");
}

function buildGraphLayout(locations) {
	const layout = new Map();
	const total = Math.max(locations.length, 1);
	const centerX = GRAPH_WIDTH / 2;
	const centerY = GRAPH_HEIGHT / 2;
	const radius = Math.max(180, Math.min(270, 180 + total * 12));
	if (total === 1) {
		const onlyId = String(locations[0]?.location_id || "");
		layout.set(onlyId, { x: centerX, y: centerY });
		return layout;
	}
	locations.forEach((loc, index) => {
		const angle = (-Math.PI / 2) + (index / total) * Math.PI * 2;
		layout.set(String(loc.location_id || ""), {
			x: centerX + Math.cos(angle) * radius,
			y: centerY + Math.sin(angle) * radius,
		});
	});
	return layout;
}

function getOrCreateLayout(frame, locations, paths) {
	const key = buildLayoutKey(frame, locations, paths);
	state.activeLayoutKey = key;
	if (!state.layoutCacheByKey[key]) {
		const base = buildGraphLayout(locations);
		const persisted = loadLayoutFromStorageByKey(key);
		if (persisted && typeof persisted === "object") {
			const normalized = normalizePersistedLayoutForCanvas(persisted);
			for (const loc of locations) {
				const id = String(loc.location_id || "");
				const p = normalized[id];
				if (!p || typeof p !== "object") {
					continue;
				}
				const x = Number(p.x);
				const y = Number(p.y);
				if (Number.isFinite(x) && Number.isFinite(y)) {
					base.set(id, clampPoint({ x, y }));
				}
			}
		}
		state.layoutCacheByKey[key] = base;
	}
	state.activeLayout = state.layoutCacheByKey[key];
	return state.activeLayout;
}

function normalizePersistedLayoutForCanvas(persisted) {
	const entries = Object.entries(persisted || {}).filter(([, value]) => value && typeof value === "object");
	const points = entries.map(([, value]) => ({ x: Number(value.x), y: Number(value.y) })).filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
	if (!points.length) {
		return persisted;
	}
	const maxX = Math.max(...points.map((point) => point.x));
	const maxY = Math.max(...points.map((point) => point.y));
	const minX = Math.min(...points.map((point) => point.x));
	const minY = Math.min(...points.map((point) => point.y));
	const looksLikeLegacyViewport = minX >= 0 && minY >= 0 && maxX <= 1300 && maxY <= 800;
	if (!looksLikeLegacyViewport) {
		return persisted;
	}
	const dx = GRAPH_WIDTH / 2 - 600;
	const dy = GRAPH_HEIGHT / 2 - 337.5;
	return Object.fromEntries(entries.map(([id, value]) => [id, { x: Number(value.x) + dx, y: Number(value.y) + dy }]));
}

function attachCanvasViewportHandlers() {
	worldGrid.onpointerdown = onCanvasPointerDown;
	worldGrid.onwheel = onCanvasWheel;
}

function onCanvasPointerDown(event) {
	if (!(event instanceof PointerEvent)) {
		return;
	}
	const target = event.target;
	if (target instanceof Element && target.closest(".location-node, button, input, [data-path-key]")) {
		return;
	}
	event.preventDefault();
	state.viewport.panning = {
		pointerId: event.pointerId,
		startClientX: event.clientX,
		startClientY: event.clientY,
		originX: Number(state.viewport.x) || 0,
		originY: Number(state.viewport.y) || 0,
	};
	worldGrid.classList.add("panning");
	worldGrid.setPointerCapture(event.pointerId);
	worldGrid.onpointermove = onCanvasPointerMove;
	worldGrid.onpointerup = onCanvasPointerUp;
	worldGrid.onpointercancel = onCanvasPointerUp;
}

function onCanvasPointerMove(event) {
	const pan = state.viewport.panning;
	if (!(event instanceof PointerEvent) || !pan || event.pointerId !== pan.pointerId) {
		return;
	}
	state.viewport.x = pan.originX + event.clientX - pan.startClientX;
	state.viewport.y = pan.originY + event.clientY - pan.startClientY;
	updateGraphStageTransform();
}

function onCanvasPointerUp(event) {
	const pan = state.viewport.panning;
	if (event instanceof PointerEvent && pan && event.pointerId !== pan.pointerId) {
		return;
	}
	state.viewport.panning = null;
	worldGrid.classList.remove("panning");
	worldGrid.onpointermove = null;
	worldGrid.onpointerup = null;
	worldGrid.onpointercancel = null;
}

function onCanvasWheel(event) {
	if (!(event instanceof WheelEvent)) {
		return;
	}
	event.preventDefault();
	const oldScale = Math.max(0.35, Math.min(2.4, Number(state.viewport.scale) || 1));
	const factor = event.deltaY < 0 ? 1.08 : 0.92;
	const nextScale = Math.max(0.35, Math.min(2.4, oldScale * factor));
	if (Math.abs(nextScale - oldScale) < 0.001) {
		return;
	}
	const rect = worldGrid.getBoundingClientRect();
	const cx = event.clientX - rect.left - rect.width / 2;
	const cy = event.clientY - rect.top - rect.height / 2;
	state.viewport.x = cx - (cx - state.viewport.x) * (nextScale / oldScale);
	state.viewport.y = cy - (cy - state.viewport.y) * (nextScale / oldScale);
	state.viewport.scale = nextScale;
	updateGraphStageTransform();
}

function updateGraphStageTransform() {
	const stage = worldGrid.querySelector(".graph-stage");
	if (stage instanceof HTMLElement) {
		stage.style.transform = graphTransformStyle();
	}
}

function buildLayoutKey(frame, locations, paths) {
	const locationIds = locations.map((x) => String(x.location_id || "")).sort().join("|");
	return `global::${locationIds}`;
}

function buildGraphEdges(paths, layout, activeTravel) {
	const dedup = new Set();
	const fragments = [];
	for (const path of paths) {
		const fromId = String(path.from_location_id || "");
		const toId = String(path.to_location_id || "");
		if (!fromId || !toId || fromId === toId) {
			continue;
		}
		const pairKey = [fromId, toId].sort().join("::");
		if (dedup.has(pairKey)) {
			continue;
		}
		dedup.add(pairKey);
		const from = layout.get(fromId);
		const to = layout.get(toId);
		if (!from || !to) {
			continue;
		}
		const pathKey = buildPathKey(path);
		const midX = (from.x + to.x) / 2;
		const midY = (from.y + to.y) / 2;
		const isActive = !!activeTravel && (
			(String(activeTravel.fromLocationId || "") === fromId && String(activeTravel.toLocationId || "") === toId) ||
			(String(activeTravel.fromLocationId || "") === toId && String(activeTravel.toLocationId || "") === fromId)
		);
		const isSelected = state.selectedPathKey === pathKey;
		const label = pathLabel(path);
		fragments.push(`
			<line class="graph-edge${isActive ? " active" : ""}${isSelected ? " selected" : ""}" data-path-key="${escapeHtml(pathKey)}" x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}"></line>
			<text class="graph-edge-label${isSelected ? " selected" : ""}" data-path-key="${escapeHtml(pathKey)}" x="${midX}" y="${midY - 8}">${escapeHtml(label)}</text>
		`);
	}
	return fragments.join("");
}

function buildPathKey(path) {
	const fromId = String(path?.from_location_id || "");
	const toId = String(path?.to_location_id || "");
	const pair = [fromId, toId].sort().join("::");
	return `${pair}::${String(path?.travel_type || "")}::${String(path?.distance ?? "")}`;
}

function pathLabel(path) {
	const parts = [];
	if (path?.travel_type) {
		parts.push(String(path.travel_type));
	}
	const cost = pathMoveCost(path);
	if (cost) {
		parts.push(cost);
	}
	return parts.join(" · ") || "path";
}

function pathMoveCost(path) {
	const value = path?.move_cost ?? path?.movement_cost ?? path?.cost ?? path?.distance ?? "";
	return value === "" || value === null || value === undefined ? "" : String(value);
}

function findPathByKey(frame, key) {
	for (const path of Array.isArray(frame?.world?.paths) ? frame.world.paths : []) {
		if (buildPathKey(path) === key) {
			return path;
		}
	}
	return null;
}

function startNodeDrag(event, node) {
	if (!(event instanceof PointerEvent)) {
		return;
	}
	const target = event.target;
	if (target instanceof HTMLElement && target.closest("button")) {
		return;
	}
	const locationId = String(node.dataset.locationId || "");
	if (!locationId || !state.activeLayout) {
		return;
	}
	const point = state.activeLayout.get(locationId);
	if (!point) {
		return;
	}
	state.dragging = {
		locationId,
		pointerId: event.pointerId,
		startClientX: event.clientX,
		startClientY: event.clientY,
		originX: point.x,
		originY: point.y,
		didMove: false,
	};
	node.classList.add("dragging");
	node.setPointerCapture(event.pointerId);
	node.addEventListener("pointermove", onNodePointerMove);
	node.addEventListener("pointerup", onNodePointerUp);
	node.addEventListener("pointercancel", onNodePointerCancel);
}

function onNodePointerMove(event) {
	if (!(event instanceof PointerEvent) || !state.dragging || !state.activeLayout) {
		return;
	}
	if (event.pointerId !== state.dragging.pointerId) {
		return;
	}
	const dx = event.clientX - state.dragging.startClientX;
	const dy = event.clientY - state.dragging.startClientY;
	if (!state.dragging.didMove && (Math.abs(dx) > 2 || Math.abs(dy) > 2)) {
		state.dragging.didMove = true;
	}
	const scale = Math.max(0.0001, Number(state.activeScale) || 1);
	const next = clampPoint({ x: state.dragging.originX + dx / scale, y: state.dragging.originY + dy / scale });
	state.activeLayout.set(state.dragging.locationId, next);
	const node = event.currentTarget;
	if (node instanceof HTMLElement) {
		node.style.left = `${next.x}px`;
		node.style.top = `${next.y}px`;
	}
	scheduleEdgeRedraw();
}

function onNodePointerUp(event) {
	finishNodeDrag(event);
}

function onNodePointerCancel(event) {
	finishNodeDrag(event);
}

function finishNodeDrag(event) {
	const node = event.currentTarget;
	if (node instanceof HTMLElement) {
		node.classList.remove("dragging");
	}
	if (!(event instanceof PointerEvent) || !state.dragging) {
		return;
	}
	if (node instanceof HTMLElement) {
		node.removeEventListener("pointermove", onNodePointerMove);
		node.removeEventListener("pointerup", onNodePointerUp);
		node.removeEventListener("pointercancel", onNodePointerCancel);
	}
	const didMove = !!state.dragging.didMove;
	state.dragging = null;
	if (state.dragEdgeRedrawRaf) {
		window.cancelAnimationFrame(state.dragEdgeRedrawRaf);
		state.dragEdgeRedrawRaf = 0;
	}
	redrawGraphEdges();
	if (didMove) {
		persistActiveLayout();
	}
}

function scheduleEdgeRedraw() {
	if (state.dragEdgeRedrawRaf) {
		return;
	}
	state.dragEdgeRedrawRaf = window.requestAnimationFrame(() => {
		state.dragEdgeRedrawRaf = 0;
		redrawGraphEdges();
	});
}

function redrawGraphEdges() {
	const frame = getDisplayedFrame();
	if (!frame || !state.activeLayout) {
		return;
	}
	const paths = Array.isArray(frame.world?.paths) ? frame.world.paths : [];
	const svg = worldGrid.querySelector(".graph-svg");
	if (!(svg instanceof SVGElement)) {
		return;
	}
	svg.innerHTML = buildGraphEdges(paths, state.activeLayout, state.playback.overlay.travel);
}

function clampPoint(point) {
	const fallback = GRAPH_WIDTH / 2;
	const x = Number(point.x);
	const y = Number(point.y);
	return {
		x: Number.isFinite(x) ? x : fallback,
		y: Number.isFinite(y) ? y : fallback,
	};
}

function computeLocationNodeSize(options) {
	const title = String(options?.title || "");
	const agentCount = Math.max(0, Number(options?.agentCount) || 0);
	const otherCount = Math.max(0, Number(options?.otherCount) || 0);
	const totalCount = Math.max(0, Number(options?.totalCount) || 0);
	const titleBoost = Math.min(18, Math.max(0, title.length - 8) * 1.2);
	const densityBoost = Math.min(58, Math.sqrt(totalCount) * 9);
	const agentBoost = Math.min(28, agentCount * 6);
	const otherBoost = Math.min(24, otherCount * 2.8);
	const size = NODE_BASE_SIZE + titleBoost + densityBoost + agentBoost + otherBoost;
	return Math.max(NODE_MIN_SIZE, Math.min(NODE_MAX_SIZE, Math.round(size)));
}

function persistActiveLayout() {
	if (!state.activeLayoutKey || !state.activeLayout) {
		return;
	}
	const store = loadLayoutStore();
	store[state.activeLayoutKey] = Object.fromEntries(Array.from(state.activeLayout.entries()).map(([id, p]) => [id, { x: p.x, y: p.y }]));
	try {
		localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(store));
	} catch (_error) {
	}
}

function loadLayoutFromStorageByKey(key) {
	const store = loadLayoutStore();
	return store[key] || null;
}

function loadLayoutStore() {
	try {
		const raw = localStorage.getItem(LAYOUT_STORAGE_KEY);
		if (!raw) {
			return {};
		}
		const parsed = JSON.parse(raw);
		return parsed && typeof parsed === "object" ? parsed : {};
	} catch (_error) {
		return {};
	}
}

function isPlainObject(value) {
	return !!value && typeof value === "object" && !Array.isArray(value);
}

function isPrimitiveValue(value) {
	return value == null || typeof value === "string" || typeof value === "number" || typeof value === "boolean";
}

function formatPrimitiveValue(value) {
	if (value == null) {
		return "null";
	}
	if (typeof value === "boolean") {
		return value ? "true" : "false";
	}
	return String(value);
}

function renderComponentValue(value) {
	if (isPrimitiveValue(value)) {
		return escapeHtml(formatPrimitiveValue(value));
	}
	if (Array.isArray(value) && value.length <= 8 && value.every((item) => isPrimitiveValue(item))) {
		return `<div class="value-chips">${value.map((item) => `<span class="value-chip">${escapeHtml(formatPrimitiveValue(item))}</span>`).join("")}</div>`;
	}
	return `<details class="json-fold"><summary>展开查看 JSON</summary><div class="pre">${escapeHtml(JSON.stringify(value, null, 2))}</div></details>`;
}

function renderComponentCards(components) {
	if (!isPlainObject(components)) {
		return '<div class="empty">无组件覆盖</div>';
	}
	const names = Object.keys(components).sort();
	if (!names.length) {
		return '<div class="empty">无组件覆盖</div>';
	}
	return `<div class="component-list">${names.map((name) => {
		const componentData = components[name];
		const fieldEntries = isPlainObject(componentData)
			? Object.entries(componentData)
			: [["value", componentData]];
		const meta = `${fieldEntries.length} fields`;
		return `
			<div class="component-card">
				<div class="component-head">
					<div class="component-name">${escapeHtml(name)}</div>
					<div class="component-meta">${escapeHtml(meta)}</div>
				</div>
				<div class="component-kv">
					${fieldEntries.map(([field, fieldValue]) => `
						<div class="key">${escapeHtml(String(field))}</div>
						<div>${renderComponentValue(fieldValue)}</div>
					`).join("")}
				</div>
			</div>
		`;
	}).join("")}</div>`;
}

function renderDetails() {
	const frame = getDisplayedFrame();
	const playbackTarget = getPlaybackTargetFrame();
	if (!frame) {
		detailsPane.innerHTML = '<div class="empty">没有当前帧</div>';
		return;
	}
	if (frame.lazy || frame.loading) {
		detailsPane.innerHTML = '<div class="empty">正在加载当前 tick...</div>';
		return;
	}
	if (frame.error) {
		detailsPane.innerHTML = `<div class="empty">加载失败：${escapeHtml(frame.error)}</div>`;
		return;
	}
	const entityMap = buildEntityMap(frame);
	if (state.selectedPathKey) {
		const path = findPathByKey(frame, state.selectedPathKey);
		if (!path) {
			detailsPane.innerHTML = '<div class="empty">未找到路径</div>';
			return;
		}
		detailsPane.innerHTML = `
			<div class="details-block">
				<div class="details-title">Path</div>
				<div class="kv">
					<div class="key">from</div><div>${escapeHtml(String(path.from_location_id || ""))}</div>
					<div class="key">to</div><div>${escapeHtml(String(path.to_location_id || ""))}</div>
					<div class="key">travel_type</div><div>${escapeHtml(String(path.travel_type || "-"))}</div>
					<div class="key">move_cost</div><div>${escapeHtml(pathMoveCost(path) || "-")}</div>
					<div class="key">key</div><div>${escapeHtml(state.selectedPathKey)}</div>
				</div>
			</div>
			<div class="details-block">
				<div class="details-title">Snapshot</div>
				<div class="pre">${escapeHtml(JSON.stringify(path, null, 2))}</div>
			</div>
		`;
		return;
	}
	if (state.selectedEntityId) {
		const entity = entityMap.get(state.selectedEntityId);
		if (!entity) {
			detailsPane.innerHTML = '<div class="empty">未找到实体</div>';
			return;
		}
		const components = entity.component_overrides || {};
		const tags = getEntityTags(entity);
		const isAgent = tags.includes("agent");
		const agentImage = getNodeImage("agent", String(entity.instance_id || ""));
		detailsPane.innerHTML = `
			<div class="details-block">
				<div class="details-title">Entity</div>
				<div class="kv">
					<div class="key">id</div><div>${escapeHtml(String(entity.instance_id || ""))}</div>
					<div class="key">template</div><div>${escapeHtml(String(entity.template_id || ""))}</div>
					<div class="key">name</div><div>${escapeHtml(entityDisplayName(entity, entity))}</div>
					<div class="key">tags</div><div>${escapeHtml(tags.join(", ") || "-")}</div>
					<div class="key">location</div><div>${escapeHtml(findLocationIdForEntity(frame, String(entity.instance_id || "")))}</div>
					<div class="key">parent</div><div>${escapeHtml(String(entity.parent_container || ""))}</div>
				</div>
			</div>
			<div class="details-block">
				<div class="details-title">Avatar</div>
				${agentImage ? `<img class="details-image-preview" src="${escapeHtml(agentImage)}" alt="${escapeHtml(entityDisplayName(entity, entity))}">` : '<div class="empty">未设置图片</div>'}
				${isAgent ? `
					<div class="details-actions">
						<button class="details-action-btn" data-action="set-image" data-kind="agent" data-id="${escapeHtml(String(entity.instance_id || ""))}">设置图片</button>
						${agentImage ? `<button class="details-action-btn" data-action="clear-image" data-kind="agent" data-id="${escapeHtml(String(entity.instance_id || ""))}">清除图片</button>` : ""}
					</div>
				` : '<div class="empty">仅 agent 节点支持头像替换</div>'}
			</div>
			<div class="details-block">
				<div class="details-title">Components</div>
				${renderComponentCards(components)}
			</div>
		`;
		return;
	}
	if (state.selectedLocationId) {
		const location = (Array.isArray(frame.world?.locations) ? frame.world.locations : []).find((loc) => String(loc.location_id || "") === state.selectedLocationId);
		if (!location) {
			detailsPane.innerHTML = '<div class="empty">未找到地点</div>';
			return;
		}
		const locationId = String(location.location_id || "");
		const locationImage = getNodeImage("location", locationId);
		const locationEntities = Array.isArray(location.entities) ? location.entities : [];
		detailsPane.innerHTML = `
			<div class="details-block">
				<div class="details-title">Location</div>
				<div class="kv">
					<div class="key">id</div><div>${escapeHtml(String(location.location_id || ""))}</div>
					<div class="key">name</div><div>${escapeHtml(String(location.location_name || ""))}</div>
					<div class="key">entities</div><div>${locationEntities.length}</div>
				</div>
			</div>
			<div class="details-block">
				<div class="details-title">Entities</div>
				${renderLocationEntityList(locationEntities, entityMap)}
			</div>
			<div class="details-block">
				<div class="details-title">Image</div>
				${locationImage ? `<img class="details-image-preview" src="${escapeHtml(locationImage)}" alt="${escapeHtml(String(location.location_name || locationId))}">` : '<div class="empty">未设置图片</div>'}
				<div class="details-actions">
					<button class="details-action-btn" data-action="set-image" data-kind="location" data-id="${escapeHtml(locationId)}">设置图片</button>
					${locationImage ? `<button class="details-action-btn" data-action="clear-image" data-kind="location" data-id="${escapeHtml(locationId)}">清除图片</button>` : ""}
				</div>
			</div>
			<div class="details-block">
				<div class="details-title">Snapshot</div>
				<div class="pre">${escapeHtml(JSON.stringify(location, null, 2))}</div>
			</div>
		`;
		return;
	}
	detailsPane.innerHTML = `
		<div class="details-block">
			<div class="details-title">Tick</div>
			<div class="kv">
				<div class="key">stable_tick</div><div>${frame.tick}</div>
				<div class="key">time</div><div>${escapeHtml(frame.timeStr)}</div>
				<div class="key">playback</div><div>${escapeHtml(state.playback.mode)}</div>
				<div class="key">target_tick</div><div>${playbackTarget ? playbackTarget.tick : "-"}</div>
				<div class="key">run_id</div><div>${escapeHtml(frame.runId)}</div>
				<div class="key">file</div><div>${escapeHtml(frame.fileName)}</div>
			</div>
		</div>
		<div class="details-block">
			<div class="details-title">Summary</div>
			<div class="kv">
				<div class="key">locations</div><div>${Array.isArray(frame.world?.locations) ? frame.world.locations.length : 0}</div>
				<div class="key">nested entities</div><div>${Array.isArray(frame.world?.entities) ? frame.world.entities.length : 0}</div>
				<div class="key">visible logs</div><div>${state.playback.visibleLogRows.length}</div>
			</div>
		</div>
	`;
}

function renderLocationEntityList(entities, entityMap) {
	if (!Array.isArray(entities) || !entities.length) {
		return '<div class="empty">这个地点没有实体</div>';
	}
	if (!state.locationEntitiesOpen) {
		return `<button class="location-entity-summary-btn" data-action="toggle-location-entities" type="button">展开实体列表 · ${entities.length}</button>`;
	}
	const filterText = String(state.locationEntityFilter || "");
	const keyword = filterText.trim().toLowerCase();
	const rows = entities.map((entity) => {
		const entityId = String(entity.instance_id || "");
		const fullEntity = entityMap.get(entityId) || entity;
		const label = entityDisplayName(entity, fullEntity);
		const tags = getEntityTags(fullEntity);
		const templateId = String(fullEntity?.template_id || entity?.template_id || "");
		const parent = String(fullEntity?.parent_container || entity?.parent_container || "");
		const searchText = [label, entityId, templateId, parent, tags.join(" ")].join(" ").toLowerCase();
		return { entityId, fullEntity, label, tags, templateId, parent, searchText };
	}).filter((row) => !keyword || row.searchText.includes(keyword));
	const listHtml = rows.length ? rows.map((row) => {
		const meta = [row.entityId, row.tags.join(", ")].filter(Boolean).join(" · ");
		return `
			<button class="location-entity-row" data-action="select-entity" data-kind="entity" data-id="${escapeHtml(row.entityId)}">
				<span class="location-entity-name">${escapeHtml(row.label)}</span>
				<span class="location-entity-meta">${escapeHtml(meta)}</span>
				<span class="location-entity-extra">template: ${escapeHtml(row.templateId || "-")}</span>
				<span class="location-entity-extra">parent: ${escapeHtml(row.parent || "-")}</span>
			</button>
		`;
	}).join("") : '<div class="empty">没有匹配的实体</div>';
	return `
		<div class="location-entity-tools">
			<input id="locationEntityFilter" class="location-entity-filter" type="text" value="${escapeHtml(filterText)}" placeholder="筛选实体">
			<button class="details-action-btn" data-action="toggle-location-entities" type="button">收起</button>
		</div>
		<div class="location-entity-count">${rows.length} / ${entities.length}</div>
		<div class="location-entity-list">${listHtml}</div>
	`;
}

function renderLog() {
	logList.innerHTML = "";
	if (!state.frames.length) {
		logList.innerHTML = '<div class="empty">没有当前帧</div>';
		return;
	}
	const rows = Array.isArray(state.playback.visibleLogRows) ? state.playback.visibleLogRows : [];
	const filteredRows = rows.filter((row) => {
		const kind = String(row.kind || "unknown");
		const kindPass =
			(kind === "interaction" && state.logFilter.showInteraction) ||
			(kind === "event" && state.logFilter.showEvent) ||
			(kind !== "interaction" && kind !== "event");
		if (!kindPass) {
			return false;
		}
		if (kind === "event") {
			const eventType = getRowEventType(row);
			if (eventType && state.logFilter.selectedEventTypes[eventType] === false) {
				return false;
			}
		}
		const keyword = String(state.logFilter.keyword || "").trim().toLowerCase();
		if (!keyword) {
			return true;
		}
		const text = formatLogRow(row).toLowerCase();
		return text.includes(keyword);
	});
	if (!rows.length) {
		if (state.playback.mode === "playing" || state.playback.mode === "paused") {
			logList.innerHTML = '<div class="empty">当前播放段尚未追加日志</div>';
			return;
		}
		logList.innerHTML = '<div class="empty">当前 tick 没有增量 log</div>';
		return;
	}
	if (!filteredRows.length) {
		logList.innerHTML = '<div class="empty">筛选后无结果</div>';
		return;
	}
	for (const row of filteredRows) {
		const kind = String(row.kind || "unknown");
		const item = document.createElement("div");
		item.className = "log-item " + kind;
		item.innerHTML = `
			<div>${escapeHtml(formatLogRow(row))}</div>
			<div class="muted">seq=${escapeHtml(String(row.seq ?? ""))} tick=${escapeHtml(String(row.tick ?? ""))}</div>
		`;
		logList.appendChild(item);
	}
}

function buildEntityMap(frame) {
	if (!frame || !frame.world || typeof frame.world !== "object") {
		return new Map();
	}
	const map = new Map();
	for (const loc of Array.isArray(frame.world?.locations) ? frame.world.locations : []) {
		for (const entity of Array.isArray(loc.entities) ? loc.entities : []) {
			map.set(String(entity.instance_id || ""), entity);
		}
	}
	for (const entity of Array.isArray(frame.world?.entities) ? frame.world.entities : []) {
		map.set(String(entity.instance_id || ""), entity);
	}
	return map;
}

function getEntityTags(entity) {
	const tags = entity?.component_overrides?.TagComponent?.tags;
	return Array.isArray(tags) ? tags.map((x) => String(x)) : [];
}

function entityDisplayName(entity, fullEntity) {
	const agentName = fullEntity?.component_overrides?.AgentSetting?.agent_name;
	if (agentName) {
		return String(agentName);
	}
	return String(entity?.name || fullEntity?.name || entity?.instance_id || fullEntity?.instance_id || fullEntity?.template_id || "Unnamed");
}

function getEntityAvatarLabel(label) {
	const text = String(label || "").trim();
	if (!text) {
		return "?";
	}
	return text.slice(0, 1).toUpperCase();
}

function findLocationIdForEntity(frame, entityId) {
	for (const loc of Array.isArray(frame.world?.locations) ? frame.world.locations : []) {
		for (const entity of Array.isArray(loc.entities) ? loc.entities : []) {
			if (String(entity.instance_id || "") === entityId) {
				return String(loc.location_id || "");
			}
		}
	}
	return "";
}

function formatLogRow(row) {
	if (row.kind === "interaction") {
		const actor = String(row.actor_name || row.actor_id || "Unknown");
		const verb = String(row.verb || "");
		const target = String(row.target_name || row.target_id || "");
		const status = String(row.status || "");
		const speech = String(row.speech || "");
		if (speech) {
			return `${actor}：${speech}`;
		}
		return `${actor} -> ${verb}${target ? " -> " + target : ""} [${status || "unknown"}]`;
	}
	if (row.kind === "event") {
		const event = row.event || {};
		const type = String(event.type || "UnknownEvent");
		if (type === "ConversationSpoken") {
			return `${resolveEventSpeakerName(event, row)}：${String(event.text || "")}`;
		}
		return `${type} ${JSON.stringify(event)}`;
	}
	return JSON.stringify(row);
}

function escapeHtml(value) {
	return String(value ?? "")
		.replaceAll("&", "&amp;")
		.replaceAll("<", "&lt;")
		.replaceAll(">", "&gt;")
		.replaceAll('"', "&quot;")
		.replaceAll("'", "&#39;");
}

render();
syncLogFilterUi();
