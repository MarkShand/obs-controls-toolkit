(() => {
    "use strict";
    const token = document.querySelector('meta[name="rundown-token"]').content;
    const panel = document.createElement("aside");
    const open = document.createElement("button");
    const close = document.createElement("button");
    const status = document.createElement("small");
    panel.className = "toolkit-support";
    panel.setAttribute("aria-label", "Support OBS Control Toolkit");
    panel.hidden = status.hidden = true;
    status.setAttribute("role", "status");
    open.type = close.type = "button";
    open.textContent = "☕ Buy me a coffee";
    open.title = "Open Ko-fi in your default browser";
    close.textContent = "×";
    close.setAttribute("aria-label", "Dismiss support reminder");
    panel.append(open, close, status);
    document.body.append(panel);

    let slot, busy = false, revision = 0;
    const notifications = typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel("toolkit-support");
    if (notifications) notifications.onmessage = () => refresh();

    function render(next) {
        slot = next;
        panel.hidden = !slot;
    }

    async function request(body) {
        const response = await fetch("/support-reminder", {
            method: body ? "POST" : "GET", cache: "no-store",
            headers: {"X-Rundown": token, "Content-Type": "application/json"}, body
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Support reminder unavailable.");
        return data.slot;
    }

    async function refresh() {
        if (busy) return;
        const ticket = ++revision;
        try {
            const next = await request();
            if (ticket === revision) render(next);
        } catch {
            if (ticket === revision) render(null);
        }
    }

    async function perform(action) {
        if (busy || !slot) return;
        busy = open.disabled = close.disabled = true;
        status.hidden = true;
        revision++;
        try {
            render(await request(JSON.stringify({action, slot})));
            notifications?.postMessage("changed");
        } catch (error) {
            status.textContent = error.message;
            status.hidden = false;
        } finally {
            busy = open.disabled = close.disabled = false;
        }
    }

    open.onclick = () => perform("open");
    close.onclick = () => perform("dismiss");
    document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
    refresh();
    setInterval(refresh, 15000);
})();
