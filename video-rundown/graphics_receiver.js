"use strict";

const renderGraphic = graphicsRenderer(document.getElementById("output"));
const [, , kind, target] = location.pathname.split("/");
let revision = "";
let eventId, previewEventId, obsActive = false, latestFrame;
const compact = new URLSearchParams(location.search).get("compact") === "1";

function drawFrame(frame, first, suppressAnimation=false) {
    const draft = !obsActive && frame.preview;
    const event = draft ? draft.event : frame.event;
    const alreadyPlayed = draft ? previewEventId : eventId;
    const animate = !suppressAnimation && event && event.id!==alreadyPlayed && !event.cut &&
        (draft || !first || (event.scene && Date.now()-event.at<12000));
    eventId = frame.event?.id;
    previewEventId = draft?.event?.id;
    const content = draft || frame;
    renderGraphic({kind:frame.kind,style:content.style,items:content.items,compact},animate ? event.action : undefined);
}

window.addEventListener("obsSourceActiveChanged", event=>{
    obsActive = Boolean(event.detail?.active);
    if (obsActive && latestFrame?.preview) {
        drawFrame(latestFrame,false,true);
        revision = "";
    }
});

async function pollGraphics() {
    try {
        const response = await fetch(`/graphics-output/${kind}/${target}?revision=${revision}`, {
            cache:"no-store", signal:AbortSignal.timeout(2500)
        });
        if (response.status === 200) {
            const frame = await response.json();
            const first = !revision;
            revision = frame.revision;
            latestFrame = frame;
            drawFrame(frame,first);
        } else if (response.status !== 204) {
            throw new Error("Graphic is unavailable.");
        }
    } catch {
        revision = "";
        latestFrame = undefined;
        renderGraphic(null);
    } finally {
        setTimeout(pollGraphics,250);
    }
}

pollGraphics();
