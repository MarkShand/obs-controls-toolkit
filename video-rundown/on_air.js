function createOnAirMonitor(redraw) {
    const get = id => document.getElementById(id);
    const mode = get("air-mode"), audio = get("air-audio"), start = get("air-play");
    const video = get("air-video"), frame = get("frame");
    const preference = "rundown-on-air-mode";
    let source = null, requestedFrame = null, pendingFrame = false, playingRequest = false;
    let air, delay, received, playBlocked = false;

    try { if (localStorage.getItem(preference) === "smooth") mode.value = "smooth"; } catch {}
    mode.onchange = () => {
        try { localStorage.setItem(preference, mode.value); } catch {}
        redraw();
    };

    function play() {
        if (playingRequest || !video.paused || playBlocked) return;
        playingRequest = true;
        const requestSource = source;
        video.play().catch(error => {
            if (source === requestSource && error.name === "NotAllowedError") {
                playBlocked = true;
                start.hidden = false;
            }
        }).finally(() => { playingRequest = false; });
    }

    function playback() {
        if (!source || !air || video.error || video.readyState < 1) return;
        const playing = air.status === "Playing";
        const target = Math.min(Number.isFinite(video.duration) ? video.duration : Infinity,
            (air.cursor + (playing ? Math.min(1000, delay + performance.now() - received) : 0)) / 1000);
        const drift = target - video.currentTime;
        if (!video.seeking && Math.abs(drift) > (playing && !video.paused ? 0.7 : 0.12)) video.currentTime = target;
        if (playing) play();
        else video.pause();
    }

    audio.onclick = () => {
        video.muted = !video.muted;
        audio.textContent = video.muted ? "Unmute On Air" : "Mute On Air";
        if (air?.status === "Playing") { playBlocked = false; play(); }
    };
    start.onclick = () => { playBlocked = false; start.hidden = true; play(); };
    video.onloadedmetadata = redraw;
    video.onerror = redraw;

    function frameKey() { return air ? air.id + "/" + air.revision : null; }

    frame.onload = () => {
        pendingFrame = false;
        frame.hidden = !air || (mode.value !== "low" && !video.error) || requestedFrame !== frameKey();
    };
    frame.onerror = () => { pendingFrame = false; frame.hidden = true; };

    return function draw(onAir, active, sampledAt, networkDelay) {
        mode.parentElement.hidden = !active;
        air = active ? onAir : null;
        delay = networkDelay;
        received = sampledAt;
        const key = frameKey();
        const nextSource = key && mode.value === "smooth" ? "/on-air-media/" + key : null;
        if (source !== nextSource) {
            source = nextSource;
            playBlocked = false;
            start.hidden = true;
            if (source) video.src = source;
            else {
                video.pause();
                video.removeAttribute("src");
                video.load();
            }
        }
        const low = Boolean(air && (!source || video.error));
        video.hidden = audio.hidden = !source || low;
        start.hidden = !source || low || !playBlocked || air?.status !== "Playing";
        if (!low || requestedFrame !== key) frame.hidden = true;
        if (low && !pendingFrame) {
            pendingFrame = true;
            requestedFrame = key;
            frame.src = "/frame?t=" + Date.now();
        }
        if (source && !low) playback();
        if (!air) return "";
        if (low) return source ? "Browser cannot play this clip · Low FPS" : "Low FPS · Silent OBS source";
        return "Smooth · Clip audio";
    };
}
