"use strict";

const $ = id => document.getElementById(id);
const tabs = {names:"Names", headlines:"Headlines", programs:"Program", crawlers:"Crawler", clock:"Clock", date:"Date",
    master:"Master Animation", scheduler:"Scheduler", settings:"Settings"};
const entryLabels = {names:"Name", headlines:"Headline", programs:"Program name", crawlers:"Crawler text"};
const styleSections = {
    Text: {
        family:["Font","Choose the installed font used by this tab."],
        foreground:["Text color","Change the color of the main text."],
        secondary:["Description color","Change the color of the description."],
        font:["Font size","Set the main text size."],
        description_font:["Description size","Set the description size independently. Leave blank to scale it with the main text."],
        bold:["Bold","Use a heavier font weight."],
        text_case:["Display Case","Change how the text appears in Preview and OBS while keeping saved text as entered."],
        lines:["Headline lines","Set how many lines a headline can use."],
        time_format:["Time format","Choose the time format, including whether to show seconds."],
        date_format:["Date format","Choose how the date is displayed."]
    },
    Background: {
        background_size:["Background sizing","Use a manual width, fit the text and padding, or fill the entire OBS source."],
        manual_width:["Manual width (% of source)","Set how much of the source width the background uses. Longer text wraps inside it."],
        headline_height:["Headline height (% of source)","Keep this height as headlines change. Leave blank to use the source default."],
        background:["Background color","Choose the background color behind the graphic."],
        transparent:["Transparent background","Make the background fully transparent."],
        opacity:["Background opacity (%)","Adjust the background transparency without fading the text."],
        padding_mode:["Padding mode","Set the same spacing on all sides or adjust each edge."],
        padding:["All sides","Set the spacing between the text and all four background edges."],
        padding_top:["Top padding","Set the spacing above the text."],
        padding_right:["Right padding","Set the spacing to the right of the text."],
        padding_bottom:["Bottom padding","Set the spacing below the text."],
        padding_left:["Left padding","Set the spacing to the left of the text."],
        corners:["Corner radius mode","Round the corners together or set each one separately."],
        radius:["All corners radius","Set the same radius on all four corners."],
        radius_tl:["Top left radius","Round the top left corner."],
        radius_tr:["Top right radius","Round the top right corner."],
        radius_bl:["Bottom left radius","Round the bottom left corner."],
        radius_br:["Bottom right radius","Round the bottom right corner."]
    },
    Alignment: {
        horizontal:["Horizontal alignment","Place the entire graphic horizontally within its OBS source."],
        vertical:["Vertical alignment","Place the entire graphic vertically within its OBS source."],
        align:["Horizontal text alignment","Align the text inside the background."],
        text_vertical:["Vertical text alignment","Place the text at the top, middle, or bottom inside the background."],
        x:["Initial left (%)","Set the initial OBS source placement for newly created sources."],
        right:["Second receiver left (%)","Set the initial placement of the second Names receiver when it is created."],
        y:["Initial top (%)","Set the initial OBS source placement from the top of the scene."]
    },
    Animation: {
        animation:["Animation preset","Choose the effect used to show and hide the graphic."],
        direction:["Direction","Choose the edge a slide or wipe starts from."],
        duration:["Duration (ms)","Set how long the entrance or exit animation takes."]
    },
    Playback: {
        speed:["Scroll speed","Set how quickly the crawler moves."],
        separator:["Separator","Choose what appears between crawler entries."],
        interval:["Autoplay interval (seconds)","Set how long each headline is shown during autoplay."],
        advance:["Autoplay transition","Choose an animated transition or a hard cut between headlines."]
    }
};
const ranges = {x:[0,100],right:[0,100],y:[0,100],manual_width:[5,100],font:[12,180],description_font:[8,180],padding:[0,80],radius:[0,120],
    headline_height:[5,100],padding_top:[0,80],padding_right:[0,80],padding_bottom:[0,80],padding_left:[0,80],
    radius_tl:[0,120],radius_tr:[0,120],radius_bl:[0,120],radius_br:[0,120],speed:[25,1200],opacity:[0,100],duration:[50,3000],interval:[1,120]};
const sliders = new Set(["opacity","padding","padding_top","padding_right","padding_bottom","padding_left","radius","radius_tl","radius_tr","radius_br","radius_bl","speed","duration","interval"]);
const horizontalChoices = {existing:"Source default",left:"Left",center:"Center",right:"Right"};
const verticalChoices = {existing:"Source default",top:"Top",middle:"Middle",bottom:"Bottom"};
const choices = {align:{left:"Left",center:"Center",right:"Right"},horizontal:horizontalChoices,vertical:verticalChoices,
    text_vertical:{top:"Top",middle:"Middle",bottom:"Bottom"}, padding_mode:{all:"All Sides",sides:"Individual Sides"},
    background_size:{manual:"Manual Width",fit:"Fit to Text",fill:"Fill Source"},corners:{all:"All Corners",individual:"Individual Corners"},
    lines:{1:"One line",2:"Two lines"},time_format:graphicsTimeFormats,date_format:graphicsDateFormats,
    animation:{slide:"Slide",fade:"Fade",wipe:"Wipe",cut:"Hard cut"},direction:["right","left","up","down"],
    advance:{animated:"Use animation preset",cut:"Hard cut"},separator:{space:"Blank space",dot:"Dot",logo:"Uploaded logo"},
    text_case:graphicsCaseOptions};
const token = document.querySelector("meta[name=rundown-token]").content;
const renderPreview = graphicsRenderer($("preview"));
const logoField = $("logo-field");
let kind = "names", library, selected, page = 0, serial = 0, pending = false, allScenes = [], receiver, loadingScenes = false;
let settings, fontList = ["Arial"], tabFont = "Arial", globalFont = "Arial", logo = "", confirmAction, pendingCsv, mappingSerial = 0;
let toastTimer, scenePreview, previewSending=false, draft, previewMotion;
let calendar={enabled:false,plans:[],queue:[]}, scheduleDraft, scheduleSnapshot="", readingSchedule=false;
const scheduleKinds=new Set(["names","programs"]);
const repeats={once:"Once",weekly:"Weekly",monthly:"Monthly",yearly:"Yearly"};
let scheduleBusy=false;
const pageSize = 35, receiverChoice = {}, openAppearance = new Map();

function toast(action, target, detail, error=false) {
    const box=$("action-toast");
    const subject=[target,detail].filter(Boolean).join(" · ");
    box.textContent=`${action} ${error ? "failed" : "succeeded"}${subject ? " — "+subject : ""}`;
    box.dataset.error=error;
    box.hidden=false;
    clearTimeout(toastTimer);
    toastTimer=setTimeout(()=>{box.hidden=true;},error ? 4200 : 2500);
}

async function api(path, body, type="application/json") {
    const headers = {"X-Rundown":token};
    if (body !== undefined) headers["Content-Type"] = type;
    const response = await fetch(path,{method:body === undefined ? "GET" : "POST",headers,body,cache:"no-store"});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Graphics service is unavailable.");
    return result;
}

function send(targetKind,data) { return api(`/graphics-command/${targetKind}`,JSON.stringify(data)); }
function requestImport(target,file,options,type="text/csv") {
    return api(`/graphics-import/${target}?options=${encodeURIComponent(JSON.stringify(options))}`,file,type);
}

function fontPicker(container, value, onPick, tip="Choose an installed font.") {
    const details = document.createElement("details"), summary = document.createElement("summary"), search = document.createElement("input"), list = document.createElement("div");
    details.className = "font-picker";
    summary.title = tip;
    search.type = "search";
    search.placeholder = "Search installed fonts…";
    search.setAttribute("aria-label","Search installed fonts");
    list.className = "font-list";
    function display(next) {
        summary.textContent = "Font · " + next;
        summary.style.fontFamily = JSON.stringify(next) + ", Arial, sans-serif";
    }
    function draw() {
        const query = search.value.trim().toLocaleLowerCase();
        const rows = [...new Set([value,...fontList])].filter(name => name.toLocaleLowerCase().includes(query)).map(name => {
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = name;
            button.style.fontFamily = JSON.stringify(name) + ", Arial, sans-serif";
            button.onclick = () => { value = name; display(name); details.open = false; onPick(name); };
            return button;
        });
        list.replaceChildren(...rows);
    }
    display(value);
    details.ontoggle = () => { if (details.open) draw(); };
    search.oninput = draw;
    details.append(summary,search,list);
    container.replaceChildren(details);
}

function controls() {
    const ready = Boolean($("scene").value), entryReady = !entryLabels[kind] || Boolean(selected) || (kind === "crawlers" && library?.entries.length);
    $("setup").disabled = pending || !ready || !library;
    $("hide").disabled = $("auto-stop").disabled = pending || !receiver;
    $("show").disabled = pending || !receiver || !entryReady;
    $("auto-start").disabled = pending || !receiver || !library?.entries.length;
    $("entry").querySelector("button[type=submit]").disabled = $("apply-style").disabled = pending || !library;
    $("scene-preview").disabled=!receiver || !library;
}

function activeReceiverName() {
    return allScenes.find(scene=>scene.key===$("scene").value)?.sources.find(row=>row.key===receiver)?.name;
}

function drawReceivers() {
    const scene = allScenes.find(row => row.key === $("scene").value);
    const relevant = scene?.sources.filter(row => row.kind === kind) || [];
    const remembered = receiverChoice[`${kind}/${scene?.key}`];
    receiver = relevant.find(row => row.key === remembered)?.key || (relevant.length === 1 ? relevant[0].key : undefined);
    if (scenePreview && (scenePreview.scene!==scene?.key || scenePreview.target!==receiver)) stopScenePreview();
    $("receivers").classList.toggle("pads",kind === "names" && $("layout").value === "grid");
    const maker = (row, targetScene) => {
        const button = document.createElement("button");
        button.type="button";
        button.textContent = row.name + (row.enabled ? "" : " · Hidden in OBS");
        button.title = row.name;
        button.setAttribute("aria-pressed",targetScene.key === scene?.key && row.key === receiver);
        button.onclick = () => { $("scene").value = targetScene.key; receiverChoice[`${kind}/${targetScene.key}`] = row.key; drawReceivers(); };
        return button;
    };
    const empty = document.createElement("small");
    empty.textContent = "No receivers in this scene. Use Set up source to add one.";
    $("receivers").replaceChildren(...(relevant.length ? relevant.map(row => maker(row,scene)) : [empty]));
    const groups = [];
    for (const group of allScenes) {
        const rows = group.sources.filter(row => row.kind === kind);
        if (!rows.length) continue;
        const section = document.createElement("section"), title = document.createElement("h3");
        title.textContent = group.name;
        section.append(title,...rows.map(row => maker(row,group)));
        groups.push(section);
    }
    $("source-groups").replaceChildren(...groups);
    const chosen = relevant.find(row => row.key === receiver);
    const size = chosen?.compact && chosen.width && chosen.height ? [chosen.width,chosen.height] : graphicsSizes[kind];
    if (size) {
        $("preview").style.aspectRatio=size.join(" / ");
        $("preview").style.setProperty("--preview-ratio",size[0]/size[1]);
    }
    controls();
}

async function refreshScenes(report=false) {
    if (loadingScenes) return;
    loadingScenes = true;
    try {
        const previous = $("scene").value;
        const {scenes,preferred} = await api("/graphics-scenes");
        const changed = JSON.stringify(allScenes) !== JSON.stringify(scenes);
        allScenes = scenes;
        if (changed || !$("scene").options.length) {
            $("scene").replaceChildren(...scenes.map(scene => new Option(scene.name,scene.key)));
            const chosen = scenes.find(scene => scene.key === previous) || scenes.find(scene => scene.name === preferred);
            if (chosen) $("scene").value = chosen.key;
            $("scene").disabled = !scenes.length;
            drawReceivers();
            drawScheduleViews();
        }
        if (report) toast("Reload scenes","OBS",scenes.length ? "" : "No scenes found");
    } catch (error) {
        if (report) toast("Reload scenes","OBS",error.message,true);
    } finally { loadingScenes = false; }
}

function formStyle() {
    const style = {...library.style,family:tabFont,...(kind === "crawlers" ? {logo} : {})};
    for (const input of $("style-fields").querySelectorAll("input,select")) {
        if (!input.name || input.disabled || !input.validity.valid) continue;
        let value = input.value;
        if (input.type === "checkbox") value = input.checked;
        else if (["number","range"].includes(input.type) || input.name === "lines") value = value === "" ? null : Number(value);
        style[input.name] = value;
    }
    return style;
}

function entryForm() {
    const data = {text:$("text").value.trim()};
    if (kind === "names") Object.assign(data,{description:$("description").value,show_description:$("show-description").checked});
    return data;
}

function preview(action) {
    if (!library || !graphicsSizes[kind]) { draft=undefined; renderPreview(null); return; }
    const style = formStyle();
    if (settings?.override) style.family = settings.family;
    const data = entryForm();
    let items = data.text ? {main:data} : {};
    if (kind === "clock" || kind === "date") items={main:{}};
    if (kind === "crawlers" && (library.entries.length || data.text)) {
        const parts = library.entries.map(item => item.id === selected && data.text ? data.text : item.text);
        if (!selected && data.text) parts.unshift(data.text);
        items={main:{parts}};
    }
    draft={style,item:items.main ?? null,hidden:action==="hide"};
    if (action) previewMotion=action;
    else previewMotion=undefined;
    renderPreview({kind,style,items:draft.hidden ? {} : items,compact:true},action);
    if (scenePreview && action) syncScenePreview();
}

function stopScenePreview() {
    const previous=scenePreview;
    scenePreview=undefined;
    $("scene-preview").checked=false;
    if (previous && !previewSending) send(previous.kind,{action:"preview-stop",target:previous.target}).catch(()=>{});
}

async function syncScenePreview() {
    const active=scenePreview;
    if (!active || !draft || previewSending) return;
    previewSending=true;
    const motion=previewMotion;
    previewMotion=undefined;
    try {
        await send(active.kind,{...active,...draft,action:"preview",motion});
        if (!active.reported && scenePreview===active) {
            active.reported=true;
            toast("Preview on OBS Scene",active.name);
        } else if (motion && scenePreview===active) {
            toast(motion==="show" ? "Preview entrance" : "Preview exit",active.name);
        }
    } catch (error) {
        if (scenePreview===active) {
            stopScenePreview();
            toast("Preview on OBS Scene",active.name,error.message,true);
        }
    } finally {
        if (scenePreview!==active) await send(active.kind,{action:"preview-stop",target:active.target}).catch(()=>{});
        previewSending=false;
    }
}

function fillEntry(entry) {
    selected = entry?.id;
    $("text").value = entry?.text || "";
    $("description").value = entry?.description || "";
    $("show-description").checked = entry?.show_description !== false;
    renderList(); preview(); controls(); drawScheduleViews();
}

function renderList() {
    const query = $("search").value.trim().toLocaleLowerCase(), sort = $("sort").value;
    const filtered = (library?.entries || []).map((item,index) => ({item,number:index+1})).filter(({item,number}) =>
        [number,item.text,item.description].join(" ").toLocaleLowerCase().includes(query));
    if (sort !== "number") filtered.sort((a,b) => (sort === "az" ? 1 : -1)*a.item.text.localeCompare(b.item.text,undefined,{numeric:true,sensitivity:"base"}));
    page = Math.min(page,Math.max(0,Math.ceil(filtered.length/pageSize)-1));
    const rows = filtered.slice(page*pageSize,(page+1)*pageSize).map(({item,number}) => {
        const row = document.createElement("li"), button = document.createElement("button"), remove = document.createElement("button");
        row.className="entry-row";
        button.type="button";
        button.textContent = `${number}. ` + [item.text,item.description].filter(Boolean).join(" · ");
        button.title=button.textContent;
        button.setAttribute("aria-pressed",item.id===selected);
        button.onclick=()=>fillEntry(item);
        remove.type="button";
        remove.className="delete-icon";
        remove.textContent="×";
        remove.setAttribute("aria-label",`Delete ${item.text}`);
        remove.title=`Delete ${item.text}`;
        const active=kind;
        remove.onclick=()=>ask(`Delete “${item.text}” from the saved ${tabs[active]} library?`,"Delete entry",()=>perform("Delete entry",item.text,async()=>{
            await send(active,{action:"delete",id:item.id}); if (kind===active) await loadLibrary(selected===item.id ? undefined : selected);
            await refreshSchedule();
        }));
        row.append(button,remove); return row;
    });
    if (!rows.length) {
        const row=document.createElement("li"), text=document.createElement("p");
        text.textContent=query ? "No matching entries." : "No saved entries.";
        row.append(text); rows.push(row);
    }
    $("entries").replaceChildren(...rows);
    $("pages").hidden=filtered.length<=pageSize;
    $("page-label").textContent=`${page*pageSize+1}–${Math.min((page+1)*pageSize,filtered.length)} of ${filtered.length}`;
    $("previous").disabled=page===0;
    $("next").disabled=(page+1)*pageSize>=filtered.length;
}

function drawStyle(style) {
    const fields=$("style-fields"); fields.replaceChildren();
    tabFont=style.family;
    for (const [section,definitions] of Object.entries(styleSections)) {
        const details=document.createElement("details"), summary=document.createElement("summary"), grid=document.createElement("div");
        const sectionKey=kind+"/"+section;
        details.className="style-section";
        details.open=openAppearance.get(sectionKey) ?? section==="Text";
        details.ontoggle=()=>openAppearance.set(sectionKey,details.open);
        summary.textContent=section; grid.className="style-grid";
        for (const [key,[label,tip]] of Object.entries(definitions)) {
            if (!(key in style) || (key==="lines" && kind!=="headlines") ||
                (["secondary","description_font"].includes(key) && kind!=="names") || (key==="date_format" && kind==="clock")) continue;
            if (key==="family") {
                const picker=document.createElement("div");
                fontPicker(picker,tabFont,value=>{ tabFont=value; preview(); },tip);
                grid.append(picker);
            } else grid.append(styleField(key,label,tip,style[key]));
        }
        if (grid.childElementCount) {
            details.append(summary,grid);
            if (section==="Playback" && kind==="crawlers") details.append(logoField);
            fields.append(details);
        }
    }
    logo=style.logo || ""; updateLogo(); updateStyleFields();
}

function styleField(key,text,tip,value) {
    const label=document.createElement("label"), values=choices[key];
    const input=document.createElement(values ? "select" : "input");
    label.title=tip; label.dataset.field=key; input.name=key;
    if (values) {
        const options=Array.isArray(values)?values.map(option=>[option,option]):Object.entries(values);
        if (key==="text_case" && value==="sentence") options.push(["sentence","Sentence case"]);
        if (key==="background_size" && kind==="headlines") options.splice(options.findIndex(option=>option[0]==="fit"),1);
        input.replaceChildren(...options.map(([option,name])=>new Option(name,option)));
        input.value=value;
    } else if (ranges[key]) {
        input.type=sliders.has(key)?"range":"number";
        [input.min,input.max]=ranges[key];
        input.required=!["manual_width","headline_height","description_font"].includes(key);
        if (["manual_width","headline_height","description_font"].includes(key)) {
            input.placeholder=key==="description_font" ? "Auto" : "Source default";
        }
        input.value=value ?? "";
    } else if (typeof value==="boolean") {
        input.type="checkbox"; input.checked=value; label.className="check";
        label.append(input,text); return label;
    } else { input.type="color"; input.value=value; }
    label.append(text,input);
    if (input.type==="range") {
        const readout=document.createElement("output"); readout.value=input.value;
        input.addEventListener("input",()=>readout.value=input.value); label.append(readout);
    }
    return label;
}

function updateStyleFields() {
    if (!library) return;
    const style=formStyle();
    for (const [key,show] of Object.entries({manual_width:style.background_size==="manual",headline_height:style.background_size!=="fill",
        padding:style.padding_mode==="all",padding_top:style.padding_mode==="sides",padding_right:style.padding_mode==="sides",
        padding_bottom:style.padding_mode==="sides",padding_left:style.padding_mode==="sides",radius:style.corners==="all",
        radius_tl:style.corners==="individual",radius_tr:style.corners==="individual",
        radius_bl:style.corners==="individual",radius_br:style.corners==="individual"})) {
        const field=$("style-fields").querySelector(`[data-field="${key}"]`);
        if (field) {
            field.hidden=!show;
            if (["manual_width","headline_height"].includes(key)) field.querySelector("input").disabled=!show;
        }
    }
    logoField.hidden=kind!=="crawlers" || style.separator!=="logo";
}

function updateLogo() {
    $("logo-sample").hidden=!logo;
    if (logo) $("logo-sample").src=logo; else $("logo-sample").removeAttribute("src");
    $("remove-logo").disabled=!logo;
}

function drawSettings() {
    $("override").checked=settings.override;
    globalFont=settings.family;
    fontPicker($("global-font-picker"),globalFont,value=>{ globalFont=value; });
    const rows=Object.entries(settings.master).map(([key,enabled])=>{
        const label=document.createElement("label"), input=document.createElement("input");
        input.type="checkbox"; input.name=key; input.checked=enabled; label.className="check";
        label.title="Replay "+tabs[key]+" when a scene containing it goes to Program.";
        label.append(input,tabs[key]); return label;
    });
    $("master-fields").replaceChildren(...rows);
}

async function loadLibrary(keep) {
    const ticket=++serial, active=kind;
    const loaded=await api(`/graphics-library/${active === "master" ? "settings" : active}`);
    if (ticket!==serial) return;
    library=loaded; settings=loaded.settings;
    if (graphicsSizes[active]) { drawStyle(loaded.style); fillEntry(loaded.entries.find(item=>item.id===keep)); }
    else drawSettings();
    controls();
}

function switchTab(next) {
    if (scenePreview) stopScenePreview();
    serial++;
    kind=next; selected=undefined; library=undefined; page=0;
    for (const button of $("tabs").children) button.setAttribute("aria-pressed",button.dataset.kind===kind);
    $("work").hidden=!graphicsSizes[kind]; $("settings").hidden=kind!=="settings"; $("master").hidden=kind!=="master";
    $("scheduler").hidden=kind!=="scheduler";
    $("library").hidden=!entryLabels[kind]; $("layout-label").hidden=kind!=="names"; $("description-fields").hidden=kind!=="names";
    $("clear-headlines").hidden=$("auto-start").hidden=$("auto-stop").hidden=kind!=="headlines";
    logoField.hidden=true;
    $("style").append(logoField);
    $("setup").textContent=kind==="names"?"Add Names receiver":"Set up source";
    $("entry-label").textContent=entryLabels[kind] || "Text";
    $("text").maxLength=kind==="crawlers"?2000:kind==="headlines"?600:200;
    $("search").value="";
    $("style-fields").replaceChildren();
    fillEntry(null); drawReceivers();
    if (kind==="scheduler") { refreshSchedule(true); return; }
    loadLibrary().catch(error=>toast("Load",tabs[kind],error.message,true));
}

async function perform(action, target, operation) {
    if (pending || !library) return;
    pending=true; controls();
    try { toast(action,target,await operation()); }
    catch(error) { toast(action,target,error.message,true); }
    finally { pending=false; controls(); }
}

function scheduleRequest(action,data={}) {
    return send("scheduler",{...data,action:"schedule-"+action});
}

function scheduleTarget(row) {
    const scene=allScenes.find(item=>item.key===row.scene);
    const receiver=scene?.sources.find(item=>item.key===row.receiver);
    return (scene?.name || row.scene_name)+" · "+(receiver?.name || row.receiver_name);
}

function localLabel(value) {
    return new Date(value).toLocaleString(undefined,{dateStyle:"medium",timeStyle:"short"});
}

function scheduleRows(container, rows, includeName) {
    const nodes=rows.map(plan=>{
        const node=document.createElement("div"), text=document.createElement("strong");
        const target=document.createElement("small"), actions=document.createElement("div");
        const edit=document.createElement("button"), remove=document.createElement("button");
        const title=plan.graphic?.text || "Entry removed";
        node.className="schedule-row";
        text.textContent=(includeName ? title+" · " : "")+localLabel(plan.next ?? plan.start)+" · "+(plan.next ? repeats[plan.repeat] : "Completed");
        target.textContent=scheduleTarget(plan);
        actions.className="row";
        edit.type=remove.type="button"; edit.textContent="Edit"; remove.textContent="Remove";
        edit.disabled=!plan.graphic;
        edit.onclick=()=>openSchedule(plan.kind,plan.graphic,plan);
        remove.onclick=()=>ask(`Remove the schedule for “${title}” at ${localLabel(plan.start)}?`,"Remove schedule",
            ()=>runSchedule("Remove schedule",title,()=>scheduleRequest("delete",{id:plan.id})));
        actions.append(edit,remove); node.append(text,target,actions);
        return node;
    });
    if (!nodes.length) {
        const empty=document.createElement("small"); empty.textContent="No schedules.";
        nodes.push(empty);
    }
    container.replaceChildren(...nodes);
}

function drawScheduleViews() {
    const entryVisible=Boolean(selected) && scheduleKinds.has(kind);
    $("entry-schedule").hidden=!entryVisible;
    $("scheduler-enabled").checked=calendar.enabled;
    if (entryVisible) scheduleRows($("entry-plans"),calendar.plans.filter(plan=>plan.kind===kind && plan.entry===selected),false);
    if (kind==="scheduler") scheduleRows($("schedules"),calendar.plans,true);
    const next=calendar.queue[0];
    $("schedule-prompt").hidden=!next;
    if (!next) return;
    $("schedule-prompt-meta").textContent=localLabel(next.due)+" · "+(calendar.queue.length===1 ? "1 awaiting approval" : `${calendar.queue.length} awaiting approval`);
    $("schedule-prompt-title").textContent=next.graphic.text+(next.graphic.show_description && next.graphic.description ? " · "+next.graphic.description : "");
    $("schedule-prompt-target").textContent=scheduleTarget(next);
}

async function refreshSchedule(report=false) {
    if (readingSchedule) return;
    readingSchedule=true;
    try {
        const next=await api("/graphics-scheduler");
        const signature=JSON.stringify(next);
        calendar=next;
        if (signature!==scheduleSnapshot || report) {scheduleSnapshot=signature;drawScheduleViews();}
    } catch(error) {
        if (report) toast("Load schedule","Scheduler",error.message,true);
    } finally { readingSchedule=false; }
}

function scheduleReceivers(preferred) {
    const sources=allScenes.find(scene=>scene.key===$("schedule-scene").value)?.sources.filter(source=>source.kind===scheduleDraft?.kind) || [];
    $("schedule-receiver").replaceChildren(new Option("Select receiver",""),...sources.map(source=>new Option(source.name,source.key)));
    if (sources.some(source=>source.key===preferred)) $("schedule-receiver").value=preferred;
    else if (sources.length===1) $("schedule-receiver").value=sources[0].key;
}

function openSchedule(targetKind, entry, plan) {
    if (!entry) return;
    scheduleDraft={kind:targetKind,entry:entry.id,id:plan?.id};
    $("schedule-title").textContent=plan ? "Edit scheduled time" : "Add scheduled time";
    $("schedule-graphic").textContent=entry.text;
    const now=new Date(Date.now()+60000);
    now.setMinutes(now.getMinutes()-now.getTimezoneOffset());
    $("schedule-time").value=plan?.start || now.toISOString().slice(0,16);
    $("schedule-repeat").value=plan?.repeat || "once";
    const choices=allScenes.filter(scene=>scene.sources.some(source=>source.kind===targetKind));
    $("schedule-scene").replaceChildren(new Option("Select scene",""),...choices.map(scene=>new Option(scene.name,scene.key)));
    const wanted=plan?.scene || $("scene").value;
    if (choices.some(scene=>scene.key===wanted)) $("schedule-scene").value=wanted;
    else if (choices.length===1) $("schedule-scene").value=choices[0].key;
    scheduleReceivers(plan?.receiver || receiver);
    $("schedule-error").hidden=true;
    $("schedule-dialog").showModal();
}

async function runSchedule(action, subject, operation, onError) {
    if (scheduleBusy) return;
    scheduleBusy=true;
    for (const id of ["schedule-save","schedule-accept","schedule-dismiss","scheduler-enabled"]) $(id).disabled=true;
    try {
        toast(action,subject,await operation());
        await refreshSchedule(true);
    } catch(error) {
        $("scheduler-enabled").checked=calendar.enabled;
        onError?.(error.message);
        toast(action,subject,error.message,true);
    } finally {
        scheduleBusy=false;
        for (const id of ["schedule-save","schedule-accept","schedule-dismiss","scheduler-enabled"]) $(id).disabled=false;
    }
}

function exportSchedule(mode) {
    runSchedule(mode==="sample" ? "Export sample" : "Export schedules","Scheduler",async()=>{
        const {path,revealed}=await scheduleRequest(mode,{reveal:true});
        if (!revealed) ask(`The file was saved to ${path}. Open its folder to access it.`,"OK",undefined,"Export saved");
        return revealed ? "" : "Saved file path available";
    });
}

function ask(prompt, label, next, title=label) {
    const dialog=$("confirm-dialog");
    if (dialog.open) return;
    $("confirm-title").textContent=title; $("confirm-text").textContent=prompt;
    $("confirm-action").textContent=label; $("confirm-cancel").hidden=!next;
    confirmAction=next; dialog.returnValue=""; dialog.showModal();
    if (!next) $("confirm-action").focus();
}

function exportFile(format,target) {
    perform("Export",target==="settings" ? "Graphics JSON" : tabs[target]+" CSV",async()=>{
        const {path,revealed}=await send(target,{action:"export",format,reveal:true});
        if (!revealed) ask(`The file was saved to ${path}. Open its folder to access it.`,"OK",undefined,"Export saved");
        return revealed ? "" : "Saved file path available";
    });
}

function openCsv(file,target) {
    pendingCsv={file,target};
    $("csv-header").checked=true;
    $("csv-dialog").showModal();
    previewCsv();
}

async function previewCsv() {
    if (!pendingCsv) return;
    const {file,target}=pendingCsv, ticket=++mappingSerial;
    $("import-confirm").disabled=true; $("mapping-fields").replaceChildren(); $("csv-example").textContent=""; $("csv-error").textContent="";
    try {
        const {columns,sample}=await requestImport("preview",file,{header:$("csv-header").checked});
        if (ticket!==mappingSerial || !$("csv-dialog").open) return;
        const specs=[["text",entryLabels[target],new Set(["text", "name", "headline", "title", "crawler", "program", "program name"])]];
        if (target==="names") specs.push(["description","Description",new Set(["description","role","subtitle","location"])],
            ["show_description","Show description",new Set(["show_description","show description"])]);
        for (const [key,name,aliases] of specs) {
            const label=document.createElement("label"), select=document.createElement("select"); select.name=key;
            select.replaceChildren(new Option("Skip",""),...columns.map((column,index)=>new Option(`${index+1}. ${column}`,String(index))));
            const match=columns.findIndex(column=>aliases.has(column.trim().toLowerCase()));
            if (match!==-1) select.value=String(match); else if (key==="text" && columns.length===1) select.value="0";
            label.append(name,select); $("mapping-fields").append(label);
        }
        $("csv-example").textContent=sample.length ? "First record · " + sample[0].join(" | ") : "";
        $("import-confirm").disabled=false;
    } catch(error) { if (ticket===mappingSerial) $("csv-error").textContent=error.message; }
}

$("mapping-form").onsubmit=async event=>{
    event.preventDefault(); if (!pendingCsv) return;
    const {file,target}=pendingCsv;
    const mapping=Object.fromEntries([...$("mapping-fields").querySelectorAll("select")].filter(select=>select.value!=="")
        .map(select=>[select.name,Number(select.value)]));
    if (!Object.hasOwn(mapping,"text")) { $("csv-error").textContent="Map the required text field before importing."; return; }
    $("import-confirm").disabled=true;
    try {
        const result=await requestImport(target,file,{header:$("csv-header").checked,mapping});
        $("csv-dialog").close(); pendingCsv=null;
        if (kind===target) await loadLibrary(selected);
        toast("Import CSV",tabs[target],`${result.imported} ${result.imported===1 ? "entry" : "entries"}`);
    } catch(error) {
        toast("Import CSV",tabs[target],error.message,true);
        $("csv-error").textContent=error.message; $("import-confirm").disabled=false;
    }
};

for (const [value,label] of Object.entries(tabs)) {
    const button=document.createElement("button"); button.type="button"; button.dataset.kind=value;
    button.textContent=label; button.onclick=()=>switchTab(value); $("tabs").append(button);
}
function updateTabArrows() {
    const strip=$("tabs");
    $("tabs-left").disabled=strip.scrollLeft<=1;
    $("tabs-right").disabled=strip.scrollLeft+strip.clientWidth>=strip.scrollWidth-1;
}
for (const [id,direction] of [["tabs-left",-1],["tabs-right",1]]) {
    $(id).onclick=()=>$("tabs").scrollBy({left:direction*$("tabs").clientWidth*.75,behavior:"smooth"});
}
$("tabs").addEventListener("scroll",updateTabArrows,{passive:true});
new ResizeObserver(updateTabArrows).observe($("tabs"));
$("csv-kind").replaceChildren(...Object.keys(entryLabels).map(key=>new Option(tabs[key],key)));
$("confirm-dialog").onclose=()=>{ const next=confirmAction; confirmAction=null; if ($("confirm-dialog").returnValue==="accept") next?.(); };
$("csv-header").onchange=previewCsv;
$("cancel-csv").onclick=()=>{ pendingCsv=null; mappingSerial++; $("csv-dialog").close(); };
$("entry").oninput=()=>preview();
$("style").oninput=()=>{updateStyleFields(); preview();};
$("scene-preview").onchange=()=>{
    if (!$("scene-preview").checked) {
        const subject=scenePreview?.name;
        stopScenePreview(); toast("Stop OBS preview",subject); return;
    }
    scenePreview={kind,scene:$("scene").value,target:receiver,name:activeReceiverName()};
    preview(); syncScenePreview();
};
$("preview-in").onclick=()=>{preview("show"); if (!scenePreview) toast("Preview entrance",tabs[kind]);};
$("preview-out").onclick=()=>{preview("hide"); if (!scenePreview) toast("Preview exit",tabs[kind]);};
$("search").oninput=$("sort").onchange=()=>{page=0; renderList();};
$("previous").onclick=()=>{page--; renderList();}; $("next").onclick=()=>{page++; renderList();};
$("new").onclick=()=>{fillEntry(null); $("text").focus();};
$("refresh-scenes").onclick=()=>refreshScenes(true); $("scene").onchange=$("layout").onchange=drawReceivers;
$("entry").onsubmit=event=>{
    event.preventDefault(); const active=kind,data={action:"save",id:selected,...entryForm()};
    perform("Save entry",data.text.trim() || tabs[active],async()=>{
        await send(active,data); if (kind===active) { fillEntry(null); $("text").focus(); await loadLibrary(); }
        await refreshSchedule();
    });
};
$("style").onsubmit=event=>{
    event.preventDefault(); const active=kind,style=formStyle();
    perform("Apply Appearance",tabs[active],async()=>{
        await send(active,{action:"style",style});
        if (kind===active && library) library.style=style;
    });
};
$("global-font").onsubmit=event=>{
    event.preventDefault(); const updated={...settings,override:$("override").checked,family:globalFont};
    perform("Save font settings","Broadcast Graphics",async()=>{await send("settings",{action:"settings",settings:updated}); await loadLibrary();});
};
$("master-form").onsubmit=event=>{
    event.preventDefault(); const master=Object.fromEntries([...$("master-fields").querySelectorAll("input")].map(input=>[input.name,input.checked]));
    perform("Save settings","Master Animation",async()=>{await send("settings",{action:"settings",settings:{...settings,master}}); await loadLibrary();});
};
$("clear-headlines").onclick=()=>ask("Clear every saved headline? The currently displayed headline stays visible until you change or hide it.",
    "Clear headlines",()=>perform("Clear library","Headlines",async()=>{await send("headlines",{action:"clear"}); if (kind==="headlines") await loadLibrary();}));
for (const field of ["library-csv","settings-csv"]) $(field).onchange=event=>{
    const file=event.target.files[0]; event.target.value=""; if (file) openCsv(file,field==="library-csv"?kind:$("csv-kind").value);
};
$("library-export").onclick=()=>exportFile("csv",kind); $("settings-export").onclick=()=>exportFile("csv",$("csv-kind").value);
$("json-export").onclick=()=>exportFile("json","settings");
$("scheduler-enabled").onchange=()=>runSchedule($("scheduler-enabled").checked ? "Enable" : "Disable","Scheduler",
    async()=>{await scheduleRequest("toggle",{enabled:$("scheduler-enabled").checked});});
$("add-schedule").onclick=()=>openSchedule(kind,library?.entries.find(entry=>entry.id===selected));
$("schedule-scene").onchange=()=>scheduleReceivers();
$("schedule-cancel").onclick=()=>$("schedule-dialog").close();
$("schedule-form").onsubmit=event=>{
    event.preventDefault();
    const input={...scheduleDraft,start:$("schedule-time").value,repeat:$("schedule-repeat").value,
        scene:$("schedule-scene").value,receiver:$("schedule-receiver").value};
    runSchedule("Save schedule",$("schedule-graphic").textContent,async()=>{
        await scheduleRequest("save",input);
        $("schedule-dialog").close();
    },error=>{$("schedule-error").textContent=error;$("schedule-error").hidden=false;});
};
$("schedule-export").onclick=()=>exportSchedule("export");
$("schedule-sample").onclick=()=>exportSchedule("sample");
$("schedule-import").onchange=event=>{
    const file=event.target.files[0]; event.target.value="";
    if (!file) return;
    runSchedule("Import schedules","Scheduler",async()=>{
        const result=await requestImport("schedule",file,{},"application/json");
        if (scheduleKinds.has(kind)) await loadLibrary(selected);
        return `${result.imported} schedules · ${result.created} new entries`;
    });
};
for (const decision of ["accept","dismiss"]) {
    $("schedule-"+decision).onclick=()=>{
        const row=calendar.queue[0];
        if (!row) return;
        runSchedule(decision==="accept" ? "Apply scheduled change" : "Dismiss scheduled change",row.receiver_name,
            async()=>{await scheduleRequest(decision,{id:row.id});});
    };
}
$("json-file").onchange=event=>{
    const file=event.target.files[0]; event.target.value="";
    if (file) ask("Replace saved graphics entries and settings with this JSON file?", "Import JSON",()=>perform("Import JSON","Broadcast Graphics",async()=>{
        const result=await requestImport("json",file,{},"application/json"); await loadLibrary(); await refreshSchedule(); return `${result.imported} entries`;
    }));
};
$("logo").onchange=event=>{
    const file=event.target.files[0]; event.target.value=""; if (!file) return;
    if (file.size>512*1024) { toast("Choose logo","Crawler","Choose an image up to 512 KB.",true); return; }
    const reader=new FileReader(); reader.onload=()=>{if (kind==="crawlers") { logo=reader.result; updateLogo(); preview(); toast("Choose logo","Crawler",file.name); }};
    reader.onerror=()=>toast("Choose logo","Crawler","Could not read the image.",true);
    reader.readAsDataURL(file);
};
$("remove-logo").onclick=()=>{logo="";updateLogo();preview();toast("Clear logo","Crawler");};
for (const [id,action] of Object.entries({setup:"setup",show:"show",hide:"hide","auto-start":"autoplay-start","auto-stop":"autoplay-stop"})) {
    $(id).onclick=()=>{
        const active=kind,scene=$("scene").value,data={action,scene,target:receiver,id:selected};
        const label={setup:"Set up source",show:"Show",hide:"Hide","autoplay-start":"Start autoplay","autoplay-stop":"Stop autoplay"}[action];
        const subject=action==="setup" ? tabs[active] : activeReceiverName() || tabs[active];
        if (action!=="setup" && scenePreview) stopScenePreview();
        perform(label,subject,async()=>{
            const result=await send(active,data);
            if (action==="setup") {
                receiverChoice[`${active}/${scene}`]=result.key; await refreshScenes();
                if (kind===active) drawReceivers();
                return `${result.source} · ${result.scene}`;
            }
        });
    };
}
switchTab("names"); refreshScenes(); setInterval(()=>{if (!pending) refreshScenes();},3000);
setInterval(syncScenePreview,750);
refreshSchedule(); setInterval(()=>{if (!scheduleBusy) refreshSchedule();},1500);
window.addEventListener("pagehide",()=>stopScenePreview());
api("/graphics-fonts").then(result=>fontList=result.fonts).catch(()=>{});
