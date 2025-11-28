const form = document.getElementById("search-form");
const resultsContainer = document.getElementById("results");
const statusEl = document.getElementById("status");
const quotaEl = document.getElementById("quota");
const shareButton = document.getElementById("share-discord");
const saveButton = document.getElementById("save-snapshot");
const clearButton = document.getElementById("clear-archive");
const snapshotFormatSelect = document.getElementById("snapshotFormat");
const topicSelect = document.getElementById("topic");
const tokenInput = document.getElementById("appToken");
const snapshotList = document.getElementById("snapshot-list");
const snapshotEmptyState = document.getElementById("snapshot-empty");
const refreshSnapshotsBtn = document.getElementById("refresh-snapshots");
const bodyEl = document.body;

const SETTINGS_KEY = "ytExplorerSettings";
const TOKEN_KEY = "ytExplorerToken";
const tokenRequired = bodyEl?.dataset?.tokenRequired === "1";

let lastSnapshot = null;

const formatDate = (value) => {
    if (!value) {
        return "Unknown publish date";
    }
    const date = new Date(value);
    return date.toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
    });
};

const formatViews = (value) => {
    if (typeof value !== "number") {
        value = Number(value) || 0;
    }
    return `${new Intl.NumberFormat().format(value)} views`;
};

const setStatus = (message, type = "info") => {
    if (!statusEl) return;
    statusEl.textContent = message;
    statusEl.className = `status status--${type}`;
};

const setQuota = (value) => {
    if (!quotaEl) return;
    if (value === undefined || value === null) {
        quotaEl.textContent = "";
        return;
    }
    quotaEl.textContent = `Estimated quota cost: ${value} unit${value === 1 ? "" : "s"}.`;
};

const getActionToken = () => {
    return (tokenInput?.value?.trim() || localStorage.getItem(TOKEN_KEY) || "").trim();
};

const buildAuthHeaders = () => {
    const token = getActionToken();
    return token ? { "X-App-Token": token } : {};
};

const canRunProtectedActions = () => !tokenRequired || Boolean(getActionToken());

const setResultActionState = (hasResults) => {
    const enabled = hasResults && canRunProtectedActions();
    if (shareButton) {
        shareButton.disabled = !enabled;
    }
    if (saveButton) {
        saveButton.disabled = !enabled;
    }
};

const persistSettings = () => {
    if (!form) return;
    const formData = new FormData(form);
    const settings = {
        query: formData.get("query") || "",
        dateRange: formData.get("dateRange") || "",
        duration: formData.get("duration") || "",
        maxResults: formData.get("maxResults") || "",
        snapshotFormat: snapshotFormatSelect?.value || "text",
        topic: topicSelect?.value || "none",
    };
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
};

const restoreSettings = () => {
    const saved = localStorage.getItem(SETTINGS_KEY);
    if (!saved) return;
    let parsed;
    try {
        parsed = JSON.parse(saved);
    } catch {
        return;
    }
    if (!parsed) {
        return;
    }
    if (parsed.query && form?.query) {
        form.query.value = parsed.query;
    }
    if (parsed.dateRange && form?.dateRange) {
        form.dateRange.value = parsed.dateRange;
    }
    if (parsed.duration && form?.duration) {
        form.duration.value = parsed.duration;
    }
    if (parsed.maxResults && form?.maxResults) {
        form.maxResults.value = parsed.maxResults;
    }
    if (parsed.snapshotFormat && snapshotFormatSelect) {
        snapshotFormatSelect.value = parsed.snapshotFormat;
    }
    if (parsed.topic && topicSelect) {
        topicSelect.value = parsed.topic;
    }
};

const persistToken = () => {
    if (!tokenInput) return;
    const value = tokenInput.value.trim();
    if (value) {
        localStorage.setItem(TOKEN_KEY, value);
    } else {
        localStorage.removeItem(TOKEN_KEY);
    }
    setResultActionState(Boolean(lastSnapshot?.items?.length));
};

const restoreToken = () => {
    if (!tokenInput) return;
    const saved = localStorage.getItem(TOKEN_KEY) || "";
    if (saved) {
        tokenInput.value = saved;
    }
};

const renderResults = (items = []) => {
    resultsContainer.innerHTML = "";
    if (!items.length) {
        setStatus("No videos matched the current filters.", "muted");
        setResultActionState(false);
        return;
    }

    const fragment = document.createDocumentFragment();
    items.forEach((item) => {
        const card = document.createElement("article");
        card.className = "result-card";
        card.innerHTML = `
            <img src="${item.thumbnail ?? ""}" alt="" loading="lazy" class="thumbnail" />
            <div class="result-body">
                <a href="${item.url}" target="_blank" rel="noopener" class="result-title">${item.title ?? "Untitled video"}</a>
                <p class="result-meta">${item.channelTitle ?? "Unknown channel"} • ${formatDate(item.publishedAt)} • ${formatViews(item.viewCount)}</p>
                <p class="result-description">${item.description ?? "No description available."}</p>
            </div>
        `;
        fragment.appendChild(card);
    });
    resultsContainer.appendChild(fragment);
};

const handleSubmit = async (event) => {
    event.preventDefault();
    if (!form) return;

    const formData = new FormData(form);
    const topicKey = formData.get("topic") || "none";
    const query = (formData.get("query") || "").trim();

    if (!query && topicKey === "none") {
        setStatus("Enter a search query or select the gaming topic filter.", "error");
        return;
    }

    const payload = {
        query,
        dateRange: formData.get("dateRange"),
        duration: formData.get("duration"),
        topic: topicKey,
        maxResults: Number(formData.get("maxResults")) || 12,
    };

    setStatus("Searching YouTube…");
    resultsContainer.innerHTML = "";
    setResultActionState(false);
    lastSnapshot = null;
    setQuota(null);

    try {
        const response = await fetch("/api/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        if (!response.ok) {
            const errorPayload = await response.json().catch(() => ({}));
            throw new Error(errorPayload.error || "Request failed.");
        }

        const data = await response.json();
        renderResults(data.items);
        setStatus(`Found ${data.items.length} video${data.items.length === 1 ? "" : "s"}.`, "success");
        setQuota(data.quotaUsed);
        lastSnapshot = { ...payload, items: data.items };
        persistSettings();
        setResultActionState(Boolean(data.items.length));
    } catch (error) {
        console.error(error);
        setStatus(error.message || "Unexpected error.", "error");
        setResultActionState(false);
    } finally {
        fetchSnapshotList();
    }
};

const sendToDiscord = async () => {
    if (!lastSnapshot || !lastSnapshot.items?.length) {
        setStatus("Run a search before sending to Discord.", "muted");
        return;
    }

    setStatus("Sending snapshot to Discord…");
    setResultActionState(false);
    try {
        const response = await fetch("/api/notify", {
            method: "POST",
            headers: { "Content-Type": "application/json", ...buildAuthHeaders() },
            body: JSON.stringify(lastSnapshot),
        });
        if (!response.ok) {
            const errorPayload = await response.json().catch(() => ({}));
            throw new Error(errorPayload.error || "Discord request failed.");
        }
        setStatus("Sent the latest search to Discord.", "success");
    } catch (error) {
        console.error(error);
        setStatus(error.message || "Unable to send to Discord.", "error");
    } finally {
        setResultActionState(Boolean(lastSnapshot?.items?.length));
    }
};

const saveSnapshotToDisk = async () => {
    if (!lastSnapshot || !lastSnapshot.items?.length) {
        setStatus("Run a search before saving.", "muted");
        return;
    }

    setStatus("Saving snapshot to disk…");
    setResultActionState(false);
    try {
        const response = await fetch("/api/save", {
            method: "POST",
            headers: { "Content-Type": "application/json", ...buildAuthHeaders() },
            body: JSON.stringify({
                ...lastSnapshot,
                format: snapshotFormatSelect?.value || "text",
            }),
        });
        if (!response.ok) {
            const errorPayload = await response.json().catch(() => ({}));
            throw new Error(errorPayload.error || "Save failed.");
        }
        const data = await response.json();
        setStatus(`Snapshot saved to data/${data.file}.`, "success");
        fetchSnapshotList();
    } catch (error) {
        console.error(error);
        setStatus(error.message || "Unable to save snapshot.", "error");
    } finally {
        setResultActionState(Boolean(lastSnapshot?.items?.length));
    }
};

const clearArchive = async () => {
    if (!window.confirm("Delete all saved snapshots in /data?")) {
        return;
    }
    setStatus("Clearing saved snapshots…");
    try {
        const response = await fetch("/api/archive/clear", {
            method: "POST",
            headers: buildAuthHeaders(),
        });
        if (!response.ok) {
            const errorPayload = await response.json().catch(() => ({}));
            throw new Error(errorPayload.error || "Unable to clear archive.");
        }
        const data = await response.json();
        setStatus(`Removed ${data.deleted} snapshot file${data.deleted === 1 ? "" : "s"}.`, "success");
        fetchSnapshotList();
    } catch (error) {
        console.error(error);
        setStatus(error.message || "Unable to clear archive.", "error");
    }
};

const renderSnapshotList = (items = []) => {
    if (!snapshotList || !snapshotEmptyState) return;
    snapshotList.innerHTML = "";
    if (!items.length) {
        snapshotEmptyState.style.display = "block";
        return;
    }
    snapshotEmptyState.style.display = "none";
    const token = getActionToken();
    const fragment = document.createDocumentFragment();
    items.forEach((file) => {
        const li = document.createElement("li");
        const link = document.createElement("a");
        const tokenQuery = token ? `?token=${encodeURIComponent(token)}` : "";
        link.href = `/archive/${encodeURIComponent(file.name)}${tokenQuery}`;
        link.textContent = file.name;
        link.target = "_blank";
        link.rel = "noopener";
        const meta = document.createElement("span");
        const modified = new Date(file.modified);
        meta.textContent = ` ${Math.round(file.size / 1024)} KB • ${modified.toLocaleString()}`;
        meta.className = "snapshot-meta";
        li.appendChild(link);
        li.appendChild(meta);
        fragment.appendChild(li);
    });
    snapshotList.appendChild(fragment);
};

const fetchSnapshotList = async () => {
    if (!snapshotList) return;
    try {
        const response = await fetch("/api/snapshots", {
            headers: buildAuthHeaders(),
        });
        if (!response.ok) {
            throw new Error("Unable to load snapshot list.");
        }
        const data = await response.json();
        renderSnapshotList(data.items);
    } catch (error) {
        console.error(error);
        if (snapshotEmptyState) {
            snapshotEmptyState.style.display = "block";
            snapshotEmptyState.textContent = tokenRequired
                ? "Enter your app token to view saved snapshots."
                : "Unable to load snapshots.";
        }
    }
};

if (form) {
    form.addEventListener("submit", handleSubmit);
}

if (shareButton) {
    shareButton.addEventListener("click", sendToDiscord);
}

if (saveButton) {
    saveButton.addEventListener("click", saveSnapshotToDisk);
}

if (clearButton) {
    clearButton.addEventListener("click", clearArchive);
}

if (refreshSnapshotsBtn) {
    refreshSnapshotsBtn.addEventListener("click", fetchSnapshotList);
}

if (tokenInput) {
    tokenInput.addEventListener("input", persistToken);
}

restoreSettings();
restoreToken();
fetchSnapshotList();
