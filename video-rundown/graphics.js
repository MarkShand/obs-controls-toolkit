"use strict";

const $ = id => document.getElementById(id);
const tabs = {names:"Names", headlines:"Headlines", programs:"Program", crawlers:"Crawler", clock:"Clock", date:"Date",
    custom:"Custom", master:"Master Animation", scheduler:"Scheduler", settings:"Settings", about:"About"};
const entryLabels = {names:"Name", headlines:"Headline", programs:"Program name", crawlers:"Crawler text", custom:"Custom label"};
const descriptionKinds = new Set(["names","custom"]);
const colorLabels = {foreground:"Main text color",secondary:"Description text color",background:"Background color",
    description_background:"Description background color"};
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
        description_layout:["Description background layout","Keep the background close to the description or use a full-width lower band."],
        description_background:["Description background color","Choose a separate background behind the description text."],
        description_transparent:["Transparent description background","Remove the background behind the description text."],
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
    description_layout:{compact:"Compact",band:"Full-width band"},
    lines:{1:"One line",2:"Two lines"},time_format:graphicsTimeFormats,date_format:graphicsDateFormats,
    animation:{slide:"Slide",fade:"Fade",wipe:"Wipe",cut:"Hard cut"},direction:["right","left","up","down"],
    advance:{animated:"Use animation preset",cut:"Hard cut"},separator:{space:"Blank space",dot:"Dot",logo:"Uploaded logo"},
    text_case:graphicsCaseOptions};
const token = document.querySelector("meta[name=rundown-token]").content;
const renderPreview = graphicsRenderer($("preview"));
const logoField = $("logo-field");
let kind = "names", library, selected, page = 0, serial = 0, pending = false, allScenes = [], receiver, loadingScenes = false;
let setupScene, pinnedScene, setupSceneLabel = "Waiting for OBS…";
let autoplayChanges = 0;
let selectedDefaultSource, defaultSourceDraft, followDefaultSource=false;
let settings, fontList = ["Arial"], tabFont = "Arial", globalFont = "Arial", logo = "", confirmAction, pendingCsv, mappingSerial = 0;
let toastTimer, scenePreview, previewSending=false, draft, previewMotion;
let presets=[], presetScope, presetBusy=false, csvTemplates={}, batchBusy=false;
const stagedCsv=[];
let calendar={enabled:false,plans:[],queue:[],playlist:[]}, scheduleDraft, scheduleSnapshot="", readingSchedule=false;
let scheduledClips=new Map();
const collapsedScheduleGroups=new Set();
const scheduleKinds=new Set(["names","programs","custom"]);
const multipleReceivers=new Set(["names","custom"]);
const entryLayoutLabels={horizontal:"Graphic horizontal alignment",vertical:"Graphic vertical alignment",align:"Text alignment",
    animation:"Entrance and exit effect",direction:"Animation direction",duration:"Animation duration (ms)"};
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
    const entryReady = !entryLabels[kind] || Boolean(selected) || (kind === "crawlers" && library?.entries.length);
    const assigned=defaultSourceStatus();
    $("setup").disabled = pending || !setupScene || !library;
    $("hide").disabled = pending || !receiver;
    $("show").disabled = pending || !receiver || !entryReady || !assigned;
    const source=kind==="headlines" ? activeReceiver() : undefined;
    const running=source?.autoplay===true;
    const canStart=source?.autoplay===false && source.enabled && Boolean(library?.entries.length);
    $("auto-start").disabled=pending || !canStart;
    $("auto-stop").disabled=pending || !running;
    $("auto-start").classList.toggle("primary",canStart);
    $("auto-stop").classList.toggle("primary",running);
    const autoplay=$("autoplay-state");
    const message=running ? (library && !library.entries.length ? "Autoplay on · No saved headlines" : "Autoplay running")
        : source?.autoplay===false ? "Autoplay stopped" : "Autoplay status unavailable";
    autoplay.hidden=!source;
    autoplay.classList.toggle("running",running);
    if (autoplay.textContent!==message) autoplay.textContent=message;
    $("entry").querySelector("button[type=submit]").disabled = $("apply-style").disabled = pending || !library;
    $("scene-preview").disabled=!receiver || !library || !assigned;
}

function sourceValue(source) {
    return source ? `${source.scene}/${source.receiver}` : "";
}

function defaultSourceLocation() {
    const scene=allScenes.find(row=>row.key===selectedDefaultSource?.scene);
    const source=scene?.sources.find(row=>row.kind==="custom" && row.key===selectedDefaultSource?.receiver);
    return source ? {scene,source} : null;
}

function defaultSourceStatus() {
    const dirty=defaultSourceDraft!==sourceValue(selectedDefaultSource);
    const location=defaultSourceLocation();
    const matches=location && location.scene.key===controlledScene()?.key && location.source.key===receiver;
    const status=$("default-source-status");
    status.hidden=kind!=="custom" || (!dirty && !selectedDefaultSource);
    $("use-default-source").hidden=!location || matches || dirty;
    let message="";
    if (dirty) message="Save the entry to apply its new default source.";
    else if (selectedDefaultSource && !location) message="Default source unavailable. Choose an available receiver in Default Source and save the entry.";
    else if (location) message=`Default · ${location.scene.name} / ${location.source.name}${location.source.enabled ? "" : " · Hidden in OBS"}`;
    if ($("default-source-message").textContent!==message) $("default-source-message").textContent=message;
    return kind!=="custom" || (!dirty && (!selectedDefaultSource || Boolean(matches && location.source.enabled)));
}

function drawDefaultSourceOptions() {
    const choices=$("entry-source-select");
    const groups=[new Option("Manual","")];
    let found=!defaultSourceDraft;
    for (const scene of allScenes) {
        const sources=scene.sources.filter(source=>source.kind==="custom");
        if (!sources.length) continue;
        const group=document.createElement("optgroup");
        group.label=scene.name;
        for (const source of sources) {
            const value=sourceValue({scene:scene.key,receiver:source.key});
            group.append(new Option(source.name,value));
            found ||= value===defaultSourceDraft;
        }
        groups.push(group);
    }
    if (!found) groups.push(new Option("Assigned source unavailable",defaultSourceDraft));
    choices.replaceChildren(...groups);
    choices.value=defaultSourceDraft;
}

function activeReceiverName() {
    return activeReceiver()?.name;
}

function activeReceiver() {
    return controlledScene()?.sources.find(row=>row.kind===kind && row.key===receiver);
}

function controlledScene() {
    return allScenes.find(scene=>scene.key===(pinnedScene || setupScene));
}

function drawReceivers() {
    if (followDefaultSource) {
        const location=defaultSourceLocation();
        if (location) {
            pinnedScene=location.scene.key;
            receiverChoice[`${kind}/${pinnedScene}`]=location.source.key;
        }
    }
    const scene = controlledScene();
    const relevant = scene?.sources.filter(row => row.kind === kind) || [];
    const remembered = receiverChoice[`${kind}/${scene?.key}`];
    receiver = relevant.find(row => row.key === remembered)?.key || (relevant.length === 1 ? relevant[0].key : undefined);
    if (scenePreview && (scenePreview.scene!==scene?.key || scenePreview.target!==receiver)) stopScenePreview();
    $("setup-scene").textContent=setupSceneLabel;
    $("receiver-scene").textContent=scene ? "Receivers · "+scene.name : "Receivers";
    $("follow-scene").hidden=!pinnedScene;
    $("receivers").classList.toggle("pads",multipleReceivers.has(kind) && $("layout").value === "grid");
    const maker = (row, targetScene) => {
        const button = document.createElement("button");
        button.type="button";
        button.textContent = row.name + (row.enabled ? "" : " · Hidden in OBS");
        button.title = row.name;
        button.setAttribute("aria-pressed",targetScene.key === scene?.key && row.key === receiver);
        button.onclick = () => {
            followDefaultSource=false;
            if (targetScene.key!==scene?.key) pinnedScene=targetScene.key===setupScene ? undefined : targetScene.key;
            receiverChoice[`${kind}/${targetScene.key}`] = row.key;
            drawReceivers();
        };
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
    const snapshot=autoplayChanges;
    try {
        const {scenes,preferred,preview} = await api("/graphics-scenes");
        if (snapshot!==autoplayChanges) return;
        const changed = JSON.stringify(allScenes) !== JSON.stringify(scenes);
        const next=scenes.find(scene=>scene.name===preferred)?.key;
        const label=next ? `${preview ? "OBS Preview" : "OBS current scene"} · ${preferred}` : "No OBS scene selected";
        const targetChanged=next!==setupScene || label!==setupSceneLabel;
        setupScene=next; setupSceneLabel=label;
        allScenes = scenes;
        if (pinnedScene && !scenes.some(scene=>scene.key===pinnedScene)) pinnedScene=undefined;
        if (changed || targetChanged) {
            if (kind==="custom") drawDefaultSourceOptions();
            drawReceivers();
            drawScheduleViews();
        }
        if (report) toast("Reload scenes","OBS",scenes.length ? "" : "No scenes found");
    } catch (error) {
        if (snapshot!==autoplayChanges) return;
        setupScene=pinnedScene=undefined;
        setupSceneLabel="OBS scene unavailable";
        allScenes=[];
        if (kind==="custom") drawDefaultSourceOptions();
        drawReceivers();
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
    if (descriptionKinds.has(kind)) Object.assign(data,{description:$("description").value,show_description:$("show-description").checked});
    if (kind === "custom") {
        for (const input of $("entry-color-fields").querySelectorAll("input[type=color]")) data[input.name]=input.disabled ? null : input.value;
        for (const field of $("entry-layout-fields").querySelectorAll("input,select"))
            data[field.name]=field.value === "" || !field.validity.valid ? null : field.type === "number" ? Number(field.value) : field.value;
    }
    return data;
}

function preview(action) {
    if (!library || !graphicsSizes[kind]) { draft=undefined; renderPreview(null); return; }
    const style = formStyle();
    if (settings?.override) style.family = settings.family;
    if (kind === "custom") style.custom_override=settings?.custom_override;
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
    if (followDefaultSource) pinnedScene=undefined;
    selectedDefaultSource=kind==="custom" ? entry?.default_source : undefined;
    defaultSourceDraft=sourceValue(selectedDefaultSource);
    followDefaultSource=Boolean(selectedDefaultSource);
    selected = entry?.id;
    $("text").value = entry?.text || "";
    $("description").value = entry?.description || "";
    $("show-description").checked = entry?.show_description !== false;
    $("entry-color-fields").replaceChildren(...(kind==="custom" && library ? graphicsColorFields.map(key=>
        colorPicker(key,colorLabels[key],entry?.[key] || library.style[key],"Use a color saved with this entry.",entry?.[key] != null)) : []));
    $("entry-layout-fields").replaceChildren(...(kind==="custom" && library ?
        Object.entries(entryLayoutLabels).map(([key,label])=>entryLayoutField(key,label,entry?.[key])) : []));
    $("entry-color-note").textContent=settings?.custom_override
        ? "Master color override is on. The graphic uses Custom’s Appearance colors."
        : "Enable a color to override Custom’s Appearance setting for this entry.";
    if (kind==="custom") { drawDefaultSourceOptions(); drawReceivers(); }
    renderList(); preview(); controls(); drawScheduleViews();
}

function entryLayoutField(key, text, value) {
    const label=document.createElement("label"), field=document.createElement(key==="duration" ? "input" : "select");
    field.name=key;
    if (key==="duration") {
        field.type="number"; field.min=50; field.max=3000; field.placeholder="Use Appearance";
    } else {
        const values=Array.isArray(choices[key]) ? choices[key].map(option=>[option,option]) : Object.entries(choices[key]);
        field.replaceChildren(new Option("Use Appearance",""),...values.filter(([option])=>option!=="existing")
            .map(([option,name])=>new Option(name,option)));
    }
    field.value=value ?? "";
    label.append(text,field);
    return label;
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
                (["secondary","description_font"].includes(key) && !descriptionKinds.has(kind)) || (key==="date_format" && kind==="clock")) continue;
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
    if (graphicsColorFields.includes(key)) return colorPicker(key,text,value,tip);
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
    }
    label.append(text,input);
    if (input.type==="range") {
        const readout=document.createElement("output"); readout.value=input.value;
        input.addEventListener("input",()=>readout.value=input.value); label.append(readout);
    }
    return label;
}

async function copyColor(value, owner) {
    try {
        try {
            await navigator.clipboard.writeText(value);
        } catch {
            const field=document.createElement("textarea");
            field.value=value; field.className="clipboard-field";
            (owner || document.body).append(field); field.select();
            try {
                if (!document.execCommand("copy")) throw new Error("Clipboard unavailable.");
            } finally {
                field.remove();
                if (owner?.open) $("preset-select").focus();
            }
        }
        if (owner) presetMessage(`Copied ${value}`); else toast("Copy HEX",value);
    } catch {
        if (owner) presetMessage("Clipboard unavailable.",true); else toast("Copy HEX",value,"Clipboard unavailable.",true);
    }
}

function colorPicker(key,text,value,tip,enabled) {
    const field=document.createElement("div"), label=document.createElement("label");
    const row=document.createElement("div"), input=document.createElement("input"), code=document.createElement("output");
    const copy=document.createElement("button");
    field.className="color-field"; field.dataset.field=key; field.title=tip || "";
    label.textContent=text; label.htmlFor=`${key}-color-${++colorPicker.count}`;
    row.className="color-controls";
    input.type="color"; input.id=label.htmlFor; input.value=value; input.name=key;
    copy.type="button"; copy.textContent="Copy HEX"; copy.setAttribute("aria-label",`Copy HEX for ${text.toLowerCase()}`);
    const show=()=>code.value=input.value.toUpperCase();
    input.addEventListener("input",show); show();
    copy.onclick=()=>copyColor(code.value,field.closest("dialog"));
    row.append(input,code,copy); field.append(label,row);
    if (enabled!==undefined) {
        const toggle=document.createElement("label"), check=document.createElement("input");
        toggle.className="check"; check.type="checkbox"; check.checked=enabled;
        check.setAttribute("aria-label",`Use entry color for ${text.toLowerCase()}`);
        toggle.append(check,"Use entry color"); field.append(toggle);
        const update=()=>{ input.disabled=!check.checked; };
        check.addEventListener("input",update); update();
    }
    return field;
}
colorPicker.count=0;

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
    $("custom-override").checked=settings.custom_override;
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
    library=loaded; settings=loaded.settings; presets=loaded.presets; csvTemplates=loaded.csv_templates;
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
    $("about").hidden=kind!=="about";
    $("library").hidden=!entryLabels[kind]; $("layout-label").hidden=!multipleReceivers.has(kind); $("description-fields").hidden=!descriptionKinds.has(kind);
    $("entry-colors").hidden=$("entry-layout").hidden=$("entry-source").hidden=kind!=="custom";
    $("description").placeholder=kind==="custom" ? "Date, location, or other detail" : "Host, reporter, or location";
    $("clear-headlines").hidden=$("auto-start").hidden=$("auto-stop").hidden=kind!=="headlines";
    logoField.hidden=true;
    $("style").append(logoField);
    $("setup").textContent=multipleReceivers.has(kind) ? `Add ${tabs[kind]} receiver` : "Set up source";
    $("entry-label").textContent=entryLabels[kind] || "Text";
    $("text").maxLength=kind==="crawlers"?2000:kind==="headlines"?600:200;
    $("search").value="";
    $("style-fields").replaceChildren();
    fillEntry(null); drawReceivers();
    if (kind==="scheduler") { refreshSchedule(true); return; }
    if (kind==="about") return;
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

function localLabel(value, seconds=false) {
    return new Date(value).toLocaleString(undefined,{dateStyle:"medium",timeStyle:seconds ? "medium" : "short"});
}

function scheduleStatus(plan, pendingApproval) {
    if (plan.trigger==="rundown") {
        if (plan.rundown_result) return plan.rundown_result.error ? "attention" : "completed";
        return plan.clip && !scheduledClips.has(plan.clip) ? "attention" : "waiting";
    }
    return pendingApproval.has(plan.id) ? "approval" : plan.next ? "waiting" : "completed";
}

function scheduleDescription(plan, status) {
    if (plan.trigger==="rundown") {
        const result=plan.rundown_result;
        if (result) return `${result.error ? "Skipped" : "Shown"} · ${result.clip_name} · ${localLabel(result.at,true)}`;
        const clip=scheduledClips.get(plan.clip);
        return `Video Rundown · ${clip?.name || plan.clip_name || "Next clip"} · ${status==="attention" ? "Clip unavailable" : "Waiting"}`;
    }
    const date=localLabel(plan.next ?? plan.start);
    return date+" · "+(status==="approval" ? "Awaiting approval" : plan.next ? repeats[plan.repeat] : "Completed");
}

function scheduleRows(container, rows, includeName, pendingApproval) {
    const nodes=rows.map(plan=>{
        const node=document.createElement("div"), text=document.createElement("strong");
        const target=document.createElement("small"), actions=document.createElement("div");
        const edit=document.createElement("button"), remove=document.createElement("button");
        const title=plan.graphic?.text || "Entry removed";
        const details=scheduleDescription(plan,scheduleStatus(plan,pendingApproval));
        node.className="schedule-row";
        text.textContent=(includeName ? title+" · " : "")+details;
        target.textContent=scheduleTarget(plan);
        actions.className="row";
        edit.type=remove.type="button"; edit.textContent="Edit"; remove.textContent="Remove";
        edit.disabled=!plan.graphic;
        edit.onclick=()=>openSchedule(plan.kind,plan.graphic,plan);
        remove.onclick=()=>ask(`Remove the schedule for “${title}”? ${details}`,"Remove schedule",
            ()=>runSchedule("Remove schedule",title,()=>scheduleRequest("delete",{id:plan.id})));
        node.append(text,target);
        if (plan.rundown_result?.error) {
            const warning=document.createElement("small");
            warning.className="schedule-warning";
            warning.textContent=plan.rundown_result.error;
            node.append(warning);
        }
        actions.append(edit,remove); node.append(actions);
        return node;
    });
    if (!nodes.length) {
        const empty=document.createElement("small"); empty.textContent="No schedules.";
        nodes.push(empty);
    }
    container.replaceChildren(...nodes);
}

function drawScheduleGroups(pendingApproval=new Set(calendar.queue.map(row=>row.plan))) {
    const query=$("schedule-search").value.trim().toLocaleLowerCase();
    const tab=$("schedule-kind-filter").value, trigger=$("schedule-trigger-filter").value;
    const status=$("schedule-status-filter").value, sort=$("schedule-sort").value;
    const filtered=calendar.plans.filter(plan=>
        (!tab || plan.kind===tab) && (!trigger || (plan.trigger || "clock")===trigger)
        && (!status || scheduleStatus(plan,pendingApproval)===status)
        && [plan.graphic?.text,plan.graphic?.description,plan.clip_name,plan.rundown_result?.clip_name,
            scheduledClips.get(plan.clip)?.name,scheduleTarget(plan),tabs[plan.kind]]
            .join(" ").toLocaleLowerCase().includes(query));
    const time=plan=>plan.next || plan.rundown_result?.at || plan.start || "";
    const rank={approval:0,waiting:1,attention:2,completed:3};
    const compare=(a,b)=>sort==="name" ? (a.graphic?.text || "").localeCompare(b.graphic?.text || "")
        : sort==="latest" ? time(b).localeCompare(time(a))
        : rank[scheduleStatus(a,pendingApproval)]-rank[scheduleStatus(b,pendingApproval)] || time(a).localeCompare(time(b));
    const groups=[];
    for (const key of [...$("tabs").children].map(button=>button.dataset.kind)) {
        const rows=filtered.filter(plan=>plan.kind===key).sort(compare);
        if (!rows.length) continue;
        const group=document.createElement("details"), summary=document.createElement("summary"), body=document.createElement("div");
        group.className="style-section schedule-group";
        group.open=!collapsedScheduleGroups.has(key);
        group.ontoggle=()=>{ if (group.isConnected) group.open ? collapsedScheduleGroups.delete(key) : collapsedScheduleGroups.add(key); };
        summary.textContent=`${tabs[key]} (${rows.length})`;
        scheduleRows(body,rows,true,pendingApproval);
        group.append(summary,body); groups.push(group);
    }
    if (!groups.length) {
        const empty=document.createElement("small");
        empty.textContent=calendar.plans.length ? "No schedules match these filters." : "No schedules.";
        groups.push(empty);
    }
    $("schedules").replaceChildren(...groups);
}

function drawScheduleViews() {
    const entryVisible=Boolean(selected) && scheduleKinds.has(kind);
    $("entry-schedule").hidden=!entryVisible;
    $("scheduler-enabled").checked=calendar.enabled;
    const pendingApproval=new Set(calendar.queue.map(row=>row.plan));
    if (entryVisible) scheduleRows($("entry-plans"),calendar.plans.filter(plan=>plan.kind===kind && plan.entry===selected),false,pendingApproval);
    if (kind==="scheduler") drawScheduleGroups(pendingApproval);
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
        const playlistChanged=JSON.stringify(calendar.playlist)!==JSON.stringify(next.playlist);
        calendar=next;
        if (playlistChanged) scheduledClips=new Map(calendar.playlist.map(clip=>[clip.id,clip]));
        if (signature!==scheduleSnapshot || report) {scheduleSnapshot=signature;drawScheduleViews();}
        if (playlistChanged && $("schedule-dialog").open) drawSchedulePlaylist($("schedule-clip").value);
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

function drawSchedulePlaylist(preferred="") {
    const select=$("schedule-clip");
    const options=[new Option("Next clip to start on air",""),...calendar.playlist.map(clip=>new Option(clip.name,clip.id))];
    if (preferred && !calendar.playlist.some(clip=>clip.id===preferred)) {
        options.push(new Option("No longer in playlist",preferred));
    }
    select.replaceChildren(...options);
    select.value=preferred;
}

function drawScheduleTrigger() {
    const clock=$("schedule-trigger").value==="clock";
    $("schedule-clock-fields").hidden=!clock;
    $("schedule-rundown-fields").hidden=clock;
    $("schedule-time").required=clock;
}

function openSchedule(targetKind, entry, plan) {
    if (!entry) return;
    scheduleDraft={kind:targetKind,entry:entry.id,id:plan?.id};
    $("schedule-title").textContent=plan ? "Edit schedule" : "Add schedule";
    $("schedule-graphic").textContent=entry.text;
    const now=new Date(Date.now()+60000);
    now.setMinutes(now.getMinutes()-now.getTimezoneOffset());
    $("schedule-time").value=plan?.start || now.toISOString().slice(0,16);
    $("schedule-repeat").value=plan?.repeat || "once";
    $("schedule-trigger").value=plan?.trigger || "clock";
    drawSchedulePlaylist(plan?.clip || "");
    drawScheduleTrigger();
    const choices=allScenes.filter(scene=>scene.sources.some(source=>source.kind===targetKind));
    $("schedule-scene").replaceChildren(new Option("Select scene",""),...choices.map(scene=>new Option(scene.name,scene.key)));
    const binding=entry.default_source;
    const wanted=binding?.scene || plan?.scene || controlledScene()?.key;
    if (choices.some(scene=>scene.key===wanted)) $("schedule-scene").value=wanted;
    else if (choices.length===1) $("schedule-scene").value=choices[0].key;
    scheduleReceivers(binding?.receiver || plan?.receiver || receiver);
    $("schedule-scene").disabled=$("schedule-receiver").disabled=Boolean(binding);
    $("schedule-error").hidden=true;
    if (binding && ($("schedule-scene").value!==binding.scene || $("schedule-receiver").value!==binding.receiver)) {
        $("schedule-error").textContent="The entry’s default source is unavailable. Reassign it before scheduling.";
        $("schedule-error").hidden=false;
    }
    $("schedule-save").disabled=!$("schedule-error").hidden;
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

function colorsFrom(container) {
    return Object.fromEntries([...container.querySelectorAll("input[type=color]")].map(input=>[input.name,input.value]));
}

function presetMessage(message="", error=false) {
    const status=$("preset-status");
    status.textContent=message; status.hidden=!message; status.dataset.error=error;
}

function drawPresetSample() {
    const colors=colorsFrom($("preset-colors")), [title,description]=$("preset-sample").children;
    $("preset-sample").style.backgroundColor=colors.background;
    title.style.color=colors.foreground;
    description.style.color=colors.secondary; description.style.backgroundColor=colors.description_background;
}

function selectPreset(key="") {
    const select=$("preset-select");
    select.replaceChildren(new Option("Current colors",""),...presets.map(preset=>new Option(preset.name,preset.id)));
    select.value=key;
    const current=presets.find(preset=>preset.id===key);
    const style={...library.style,...(presetScope==="settings" ? {} : formStyle())};
    const entry=presetScope==="entry" ? entryForm() : {};
    const defaults={foreground:"#14171c",secondary:"#39434e",background:"#ffffff",description_background:"#e6edf5"};
    $("preset-name").value=current?.name || "";
    $("preset-colors").replaceChildren(...graphicsColorFields.map(field=>
        colorPicker(field,colorLabels[field],current?.[field] || entry[field] || style[field] || defaults[field])));
    $("preset-update").disabled=!current;
    drawPresetSample();
}

function openPresets(scope) {
    if (!library) return;
    presetScope=scope;
    $("preset-apply").hidden=scope==="settings";
    $("preset-apply").textContent=scope==="entry" ? "Apply to entry" : "Apply to Appearance";
    selectPreset(scope==="settings" ? presets[0]?.id : "");
    presetMessage(); $("preset-dialog").showModal();
}

async function savePreset(update) {
    const name=$("preset-name").value.trim();
    if (presetBusy) return;
    if (!name) { presetMessage("Enter a preset name.",true); $("preset-name").focus(); return; }
    presetBusy=true;
    $("preset-new").disabled=$("preset-update").disabled=true;
    try {
        const id=update ? $("preset-select").value : undefined;
        const result=await send("settings",{action:"preset",id,name,...colorsFrom($("preset-colors"))});
        presets=result.presets;
        if ($("preset-dialog").open) { selectPreset(result.id); presetMessage(`Saved “${name}”.`); }
    } catch (error) { presetMessage(error.message,true); }
    finally {
        presetBusy=false; $("preset-new").disabled=false; $("preset-update").disabled=!$("preset-select").value;
    }
}

$("entry-presets").onclick=()=>openPresets("entry");
$("appearance-presets").onclick=()=>openPresets("appearance");
$("settings-presets").onclick=()=>openPresets("settings");
for (const button of $("about").querySelectorAll("[data-project-link]")) {
    button.onclick=async()=>{
        button.disabled=true;
        try {
            await api("/project-link",JSON.stringify({link:button.dataset.projectLink}));
        } catch (error) {
            toast("Open link",button.textContent,error.message,true);
        } finally { button.disabled=false; }
    };
}
$("preset-select").onchange=event=>{ selectPreset(event.target.value); presetMessage(); };
$("preset-form").onsubmit=event=>event.preventDefault();
$("preset-colors").oninput=drawPresetSample;
$("preset-update").onclick=()=>savePreset(true);
$("preset-new").onclick=()=>savePreset(false);
$("preset-close").onclick=()=>$("preset-dialog").close();
$("preset-apply").onclick=()=>{
    const container=$(presetScope==="entry" ? "entry-color-fields" : "style-fields");
    for (const [key,value] of Object.entries(colorsFrom($("preset-colors")))) {
        const field=container.querySelector(`[data-field="${key}"]`);
        if (!field) continue;
        const input=field.querySelector("input[type=color]"), check=field.querySelector("input[type=checkbox]");
        if (check) { check.checked=true; check.dispatchEvent(new Event("input")); }
        input.value=value; input.dispatchEvent(new Event("input"));
    }
    for (const key of ["transparent","description_transparent"]) {
        const check=container.querySelector(`input[name="${key}"]`);
        if (check) check.checked=false;
    }
    preview(); $("preset-dialog").close();
    toast("Apply colors",tabs[kind],presetScope==="entry" ? "Save the entry to keep these colors." : "Apply Appearance to keep these colors.");
};

function csvTable(container, columns, rows) {
    container.replaceChildren();
    if (!columns.length) return;
    const table=document.createElement("table"), head=table.createTHead().insertRow(), body=table.createTBody();
    for (const column of columns) {
        const cell=document.createElement("th"); cell.scope="col"; cell.textContent=column; head.append(cell);
    }
    for (const values of rows) {
        const row=body.insertRow();
        columns.forEach((_,index)=>row.insertCell().textContent=values[index] || "");
    }
    container.append(table);
}

function csvMessage(message="") {
    $("csv-error").textContent=message; $("csv-error").hidden=!message;
    if (message) { $("csv-template").open=true; $("csv-sample").open=true; }
}

function openCsv(file,target,staged=null) {
    pendingCsv={file,target,staged};
    $("csv-title").textContent=`${tabs[target]} CSV · ${file.name}`;
    $("csv-header").checked=staged?.header ?? true;
    $("import-confirm").textContent=staged ? "Confirm mapping" : "Import entries";
    $("csv-template").open=true; $("csv-sample").open=false;
    const template=csvTemplates[target];
    csvTable($("csv-expected"),template?.columns || [],template ? [template.sample] : []);
    $("csv-dialog").showModal();
    previewCsv();
}

async function previewCsv() {
    if (!pendingCsv) return;
    const {file,target,staged}=pendingCsv, ticket=++mappingSerial, header=$("csv-header").checked;
    $("import-confirm").disabled=true; $("mapping-fields").replaceChildren(); $("csv-example").replaceChildren(); csvMessage();
    try {
        const {columns,sample,mapping,warning,empty}=await requestImport("preview",file,{header,kind:target});
        if (ticket!==mappingSerial || !$("csv-dialog").open) return;
        csvTable($("csv-example"),columns,sample);
        if (warning) { csvMessage(warning); return; }
        if (empty) { csvMessage("There are no entries in this CSV."); return; }
        const specs={text:entryLabels[target]};
        if (descriptionKinds.has(target)) Object.assign(specs,{description:"Description",show_description:"Show description"});
        if (target==="custom") Object.assign(specs,colorLabels,entryLayoutLabels);
        const defaults=staged?.target===target && staged.header===header ? staged.mapping || mapping : mapping;
        for (const [key,name] of Object.entries(specs)) {
            const label=document.createElement("label"), select=document.createElement("select"); select.name=key;
            select.replaceChildren(new Option("Skip",""),...columns.map((column,index)=>new Option(`${index+1}. ${column}`,String(index))));
            if (key in defaults) select.value=String(defaults[key]);
            else if (key==="text" && !header && columns.length===1) select.value="0";
            label.append(name,select); $("mapping-fields").append(label);
        }
        if (!("text" in defaults) && header) csvMessage("The expected text column is missing. Check the table or map the text column manually.");
        $("import-confirm").disabled=false;
    } catch(error) { if (ticket===mappingSerial) csvMessage(error.message); }
}

$("mapping-form").onsubmit=async event=>{
    event.preventDefault(); if (!pendingCsv) return;
    const active=pendingCsv, {file,target,staged}=active, header=$("csv-header").checked;
    const mapping=Object.fromEntries([...$("mapping-fields").querySelectorAll("select")].filter(select=>select.value!=="")
        .map(select=>[select.name,Number(select.value)]));
    if (!Object.hasOwn(mapping,"text")) { csvMessage("Map the required text field before importing."); return; }
    $("import-confirm").disabled=true;
    try {
        const result=await requestImport(staged ? "validate" : target,file,{kind:target,header,mapping});
        if (staged) {
            Object.assign(staged,{target,header,mapping,count:result.imported,error:""});
            drawBatch();
        }
        if (pendingCsv===active) $("csv-dialog").close();
        if (!staged) {
            if (kind===target) await loadLibrary(selected);
            toast("Import CSV",tabs[target],`${result.imported} ${result.imported===1 ? "entry" : "entries"}`);
        }
    } catch(error) {
        toast("Import CSV",tabs[target],error.message,true);
        if (pendingCsv===active) { csvMessage(error.message); $("import-confirm").disabled=false; }
    }
};

function drawBatch() {
    const list=$("batch-list");
    list.replaceChildren(...stagedCsv.map(item=>{
        const row=document.createElement("li"), name=document.createElement("strong"), status=document.createElement("small");
        const actions=document.createElement("div"), select=document.createElement("select");
        const review=document.createElement("button"), remove=document.createElement("button");
        name.textContent=item.file.name;
        status.textContent=item.error || (item.loading ? "Reading columns…" : item.empty || item.count===0 ? "Empty · will be skipped"
            : item.mapping ? `${item.count} ${item.count===1 ? "entry" : "entries"} ready` : "Choose a library and review columns.");
        status.dataset.error=Boolean(item.error);
        actions.className="batch-row-actions";
        select.setAttribute("aria-label",`Library for ${item.file.name}`);
        select.replaceChildren(new Option("Choose library",""),...Object.keys(entryLabels).map(key=>new Option(tabs[key],key)));
        select.value=item.target || "";
        select.disabled=batchBusy || item.loading || item.empty;
        select.onchange=()=>{
            Object.assign(item,{target:select.value,header:true,mapping:null,count:null,error:""});
            drawBatch();
            if (item.target) openCsv(item.file,item.target,item);
        };
        review.type=remove.type="button"; review.textContent="Review"; remove.textContent="×";
        remove.setAttribute("aria-label",`Remove ${item.file.name} from queue`);
        review.disabled=batchBusy || item.loading || item.empty || !item.target;
        review.onclick=()=>openCsv(item.file,item.target,item);
        remove.disabled=batchBusy;
        remove.onclick=()=>{stagedCsv.splice(stagedCsv.indexOf(item),1); drawBatch();};
        actions.append(select,review,remove); row.append(name,status,actions);
        return row;
    }));
    $("batch-actions").hidden=!stagedCsv.length;
    $("batch-clear").disabled=batchBusy;
    $("batch-import").disabled=batchBusy || !stagedCsv.some(item=>item.count>0)
        || stagedCsv.some(item=>item.loading || item.error || (!item.empty && !item.mapping));
    $("batch-files").disabled=batchBusy;
}

async function inspectCsv(item) {
    try {
        const info=await requestImport("preview",item.file,{header:true});
        if (info.empty && !info.columns.length) { item.empty=true; return; }
        if (info.types.length===1) {
            item.target=info.types[0];
            const {mapping}=info;
            if ("text" in mapping) {
                const result=await requestImport("validate",item.file,{header:true,kind:item.target,mapping});
                Object.assign(item,{mapping,count:result.imported});
            }
        }
    } catch (error) { item.error=error.message; }
    finally {
        item.loading=false;
        if (stagedCsv.includes(item)) drawBatch();
    }
}

function stageCsv(files) {
    if (batchBusy) return;
    let skipped=0;
    for (const file of files) {
        if (!/\.csv$/i.test(file.name) && file.type!=="text/csv") { skipped++; continue; }
        if (stagedCsv.some(item=>item.file.name===file.name && item.file.size===file.size && item.file.lastModified===file.lastModified)) continue;
        const item={file,header:true,loading:true};
        stagedCsv.push(item); inspectCsv(item);
    }
    drawBatch();
    if (skipped) toast("Stage CSV","CSV Libraries",`${skipped} ${skipped===1 ? "file was" : "files were"} skipped. Choose CSV files.`,true);
}

function readCsvBytes(file) {
    return new Promise((resolve,reject)=>{
        const reader=new FileReader();
        reader.onload=()=>resolve(reader.result.split(",",2)[1]);
        reader.onerror=()=>reject(new Error(`Could not read ${file.name}.`));
        reader.readAsDataURL(file);
    });
}

$("batch-files").onchange=event=>{ stageCsv(event.target.files); event.target.value=""; };
$("batch-clear").onclick=()=>{ stagedCsv.length=0; drawBatch(); };
const csvDrop=$("csv-drop");
csvDrop.ondragover=event=>{
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault(); event.dataTransfer.dropEffect=batchBusy ? "none" : "copy";
    csvDrop.classList.toggle("drag-over",!batchBusy);
};
csvDrop.ondragleave=event=>{ if (!csvDrop.contains(event.relatedTarget)) csvDrop.classList.remove("drag-over"); };
csvDrop.ondrop=event=>{ event.preventDefault(); csvDrop.classList.remove("drag-over"); stageCsv(event.dataTransfer.files); };
$("batch-import").onclick=async()=>{
    if ($("batch-import").disabled) return;
    const ready=stagedCsv.filter(item=>item.count>0);
    if (ready.reduce((size,item)=>size+item.file.size,0)>16*1024*1024) {
        toast("Import batch","CSV Libraries","Choose CSV files totaling up to 16 MB per batch.",true); return;
    }
    batchBusy=true; drawBatch();
    try {
        const files=await Promise.all(ready.map(async ({file,target,header,mapping})=>
            ({name:file.name,kind:target,header,mapping,data:await readCsvBytes(file)})));
        const result=await requestImport("batch",JSON.stringify(files),{},"application/json");
        const summary=Object.entries(result.counts).map(([target,count])=>`${tabs[target]} ${count}`).join(" · ");
        stagedCsv.length=0;
        if (entryLabels[kind]) await loadLibrary(selected);
        toast("Import batch","CSV Libraries",summary || "No entries to import.");
    } catch (error) { toast("Import batch","CSV Libraries",error.message,true); }
    finally { batchBusy=false; drawBatch(); }
};

const tabStrip=$("tabs"), tabOrderKey="graphics-tab-order";
let draggedTab, tabScroll=0, tabScrollFrame=0;

function saveTabOrder() {
    try { localStorage.setItem(tabOrderKey,JSON.stringify([...tabStrip.children].map(tab=>tab.dataset.kind))); } catch {}
    updateTabArrows();
}

function stopTabScroll() {
    cancelAnimationFrame(tabScrollFrame); tabScrollFrame=0; tabScroll=0;
}

function scrollTabsOnDrag() {
    tabStrip.scrollLeft+=tabScroll;
    tabScrollFrame=requestAnimationFrame(scrollTabsOnDrag);
}

tabStrip.ondragover=event=>{
    if (!draggedTab) return;
    event.preventDefault(); event.dataTransfer.dropEffect="move";
    const {left,right}=tabStrip.getBoundingClientRect();
    tabScroll=event.clientX<left+24 ? -4 : event.clientX>right-24 ? 4 : 0;
    if (!tabScroll || tabStrip.scrollWidth<=tabStrip.clientWidth) stopTabScroll();
    else if (!tabScrollFrame) tabScrollFrame=requestAnimationFrame(scrollTabsOnDrag);
};
tabStrip.ondragleave=event=>{ if (!tabStrip.contains(event.relatedTarget)) stopTabScroll(); };
tabStrip.ondrop=event=>{
    if (!draggedTab) return;
    event.preventDefault(); stopTabScroll();
    const target=[...tabStrip.children].find(button=>{
        const rect=button.getBoundingClientRect();
        return event.clientX<rect.left+rect.width/2;
    });
    if (target!==draggedTab) tabStrip.insertBefore(draggedTab,target || null);
    saveTabOrder();
};
let tabOrder=Object.keys(tabs);
try {
    const stored=JSON.parse(localStorage.getItem(tabOrderKey));
    if (Array.isArray(stored)) tabOrder=[...new Set([...stored,...tabOrder])].filter(key=>Object.hasOwn(tabs,key));
} catch {}
for (const value of tabOrder) {
    const button=document.createElement("button"); button.type="button"; button.dataset.kind=value;
    button.textContent=tabs[value]; button.onclick=()=>switchTab(value);
    button.draggable=true; button.title="Drag to reorder or press Alt+Left/Right";
    button.ondragstart=event=>{
        draggedTab=button; button.classList.add("tab-dragging");
        event.dataTransfer.setData("application/x-graphics-tab",value); event.dataTransfer.effectAllowed="move";
    };
    button.ondragend=()=>{ draggedTab=null; button.classList.remove("tab-dragging"); stopTabScroll(); };
    button.onkeydown=event=>{
        if (!event.altKey || !["ArrowLeft","ArrowRight"].includes(event.key)) return;
        const left=event.key==="ArrowLeft", neighbor=left ? button.previousElementSibling : button.nextElementSibling;
        if (!neighbor) return;
        event.preventDefault();
        tabStrip.insertBefore(button,left ? neighbor : neighbor.nextElementSibling);
        button.focus(); button.scrollIntoView({block:"nearest",inline:"nearest"}); saveTabOrder();
    };
    tabStrip.append(button);
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
$("cancel-csv").onclick=()=>$("csv-dialog").close();
$("csv-dialog").onclose=()=>{ pendingCsv=null; mappingSerial++; };
$("entry").oninput=()=>preview();
$("style").oninput=()=>{updateStyleFields(); preview();};
$("scene-preview").onchange=()=>{
    if (!$("scene-preview").checked) {
        const subject=scenePreview?.name;
        stopScenePreview(); toast("Stop OBS preview",subject); return;
    }
    scenePreview={kind,scene:controlledScene()?.key,target:receiver,name:activeReceiverName()};
    preview(); syncScenePreview();
};
$("preview-in").onclick=()=>{preview("show"); if (!scenePreview) toast("Preview entrance",tabs[kind]);};
$("preview-out").onclick=()=>{preview("hide"); if (!scenePreview) toast("Preview exit",tabs[kind]);};
$("search").oninput=$("sort").onchange=()=>{page=0; renderList();};
$("previous").onclick=()=>{page--; renderList();}; $("next").onclick=()=>{page++; renderList();};
$("new").onclick=()=>{fillEntry(null); $("text").focus();};
$("refresh-scenes").onclick=()=>refreshScenes(true); $("layout").onchange=drawReceivers;
$("follow-scene").onclick=()=>{ followDefaultSource=false; pinnedScene=undefined; drawReceivers(); };
$("use-default-source").onclick=()=>{ followDefaultSource=true; drawReceivers(); };
$("entry-source-select").onchange=event=>{
    defaultSourceDraft=event.target.value;
    if (scenePreview) stopScenePreview();
    controls();
};
$("entry").onsubmit=event=>{
    event.preventDefault(); const active=kind,data={action:"save",id:selected,...entryForm()};
    if (kind==="custom") {
        const [scene,receiver]=defaultSourceDraft.split("/");
        data.default_source=defaultSourceDraft ? {scene,receiver} : null;
    }
    perform("Save entry",data.text.trim() || tabs[active],async()=>{
        const result=await send(active,data);
        if (kind===active) { fillEntry(null); $("text").focus(); await loadLibrary(); }
        await refreshSchedule();
        if (result.schedule_conflicts) return "Update this entry’s schedules that still use the previous source.";
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
    event.preventDefault(); const updated={override:$("override").checked,family:globalFont,custom_override:$("custom-override").checked};
    perform("Save settings","Broadcast Graphics",async()=>{await send("settings",{action:"settings",settings:updated}); await loadLibrary();});
};
$("master-form").onsubmit=event=>{
    event.preventDefault(); const master=Object.fromEntries([...$("master-fields").querySelectorAll("input")].map(input=>[input.name,input.checked]));
    perform("Save settings","Master Animation",async()=>{await send("settings",{action:"settings",settings:{master}}); await loadLibrary();});
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
$("schedule-trigger").onchange=drawScheduleTrigger;
$("schedule-search").oninput=()=>drawScheduleGroups();
for (const key of ["sort","kind-filter","trigger-filter","status-filter"]) {
    $("schedule-"+key).onchange=()=>drawScheduleGroups();
}
$("schedule-scene").onchange=()=>scheduleReceivers();
$("schedule-cancel").onclick=()=>$("schedule-dialog").close();
$("schedule-form").onsubmit=event=>{
    event.preventDefault();
    const trigger=$("schedule-trigger").value;
    const timing=trigger==="rundown" ? {clip:$("schedule-clip").value || null}
        : {start:$("schedule-time").value,repeat:$("schedule-repeat").value};
    const input={...scheduleDraft,trigger,...timing,scene:$("schedule-scene").value,receiver:$("schedule-receiver").value};
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
        const active=kind,scene=action==="setup" ? setupScene : controlledScene()?.key;
        const data={action,scene,target:receiver,id:selected,follow_preview:action==="setup"};
        const label={setup:"Set up source",show:"Show",hide:"Hide","autoplay-start":"Start autoplay","autoplay-stop":"Stop autoplay"}[action];
        const subject=action==="setup" ? tabs[active] : activeReceiverName() || tabs[active];
        if (action!=="setup" && scenePreview) stopScenePreview();
        perform(label,subject,async()=>{
            const result=await send(active,data);
            if (action==="setup") {
                pinnedScene=undefined;
                receiverChoice[`${active}/${scene}`]=result.key; await refreshScenes();
                if (kind===active) drawReceivers();
                return `${result.source} · ${result.scene}`;
            }
            if (active==="headlines" && typeof result.autoplay==="boolean") {
                autoplayChanges++;
                for (const scene of allScenes) {
                    for (const source of scene.sources) {
                        if (source.kind===active && source.key===data.target) source.autoplay=result.autoplay;
                    }
                }
            }
        });
    };
}
switchTab("names"); refreshScenes(); setInterval(()=>{if (!pending) refreshScenes();},3000);
setInterval(syncScenePreview,750);
refreshSchedule(); setInterval(()=>{if (!scheduleBusy) refreshSchedule();},1500);
window.addEventListener("pagehide",()=>stopScenePreview());
api("/graphics-fonts").then(result=>fontList=result.fonts).catch(()=>{});
