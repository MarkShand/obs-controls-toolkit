"use strict";

const graphicsTimeFormats = {
    "12hm":"12-hour, hours and minutes", "12hms":"12-hour, with seconds", "12hmsms":"12-hour, with milliseconds",
    "24hm":"24-hour, hours and minutes", "24hms":"24-hour, with seconds", "24hmsms":"24-hour, with milliseconds"
};
const graphicsDateFormats = {
    long:"Weekday, full date", weekday:"Weekday, abbreviated date", short:"Abbreviated date",
    ymd:"YYYY-MM-DD", mdy:"MM/DD/YYYY", dmy:"DD/MM/YYYY"
};
const graphicsDateReaders = {
    long:new Intl.DateTimeFormat(undefined,{weekday:"long",month:"long",day:"numeric",year:"numeric"}),
    weekday:new Intl.DateTimeFormat(undefined,{weekday:"short",month:"short",day:"numeric",year:"numeric"}),
    short:new Intl.DateTimeFormat(undefined,{month:"short",day:"numeric",year:"numeric"})
};

function formatGraphicsClock(date, timeFormat, dateFormat) {
    const two = n => String(n).padStart(2,"0");
    const hours = date.getHours(), twelve = timeFormat.startsWith("12");
    let time = two(twelve ? hours % 12 || 12 : hours) + ":" + two(date.getMinutes());
    if (timeFormat.endsWith("hms") || timeFormat.endsWith("hmsms")) time += ":" + two(date.getSeconds());
    if (timeFormat.endsWith("hmsms")) time += "." + String(date.getMilliseconds()).padStart(3,"0");
    if (twelve) time += hours < 12 ? " AM" : " PM";
    const y = date.getFullYear(), m = two(date.getMonth()+1), d = two(date.getDate());
    const dates = {ymd:`${y}-${m}-${d}`, mdy:`${m}/${d}/${y}`, dmy:`${d}/${m}/${y}`};
    return {time, date:graphicsDateReaders[dateFormat]?.format(date) || dates[dateFormat] || dates.ymd};
}

const graphicsSizes = {names:[760,196],headlines:[1650,240],programs:[1040,160],crawlers:[1920,128],clock:[480,134],date:[630,134],custom:[640,176]};
const graphicsColorFields = ["foreground","secondary","background","description_background"];
const graphicsCaseOptions = {original:"As Entered",upper:"UPPERCASE",lower:"lowercase",title:"Title Case"};

function graphicsItemStyle(kind, style, item) {
    if (kind !== "custom") return style;
    const overrides = ["horizontal","vertical","align","animation","direction","duration"];
    const settings = Object.fromEntries(overrides.filter(field=>item[field]!=null).map(field=>[field,item[field]]));
    const colors = style.custom_override ? {} :
        Object.fromEntries(graphicsColorFields.filter(field=>item[field]).map(field=>[field,item[field]]));
    if (colors.background) colors.transparent=false;
    if (colors.description_background) colors.description_transparent=false;
    return {...style,...settings,...colors};
}

function graphicsTextCase(value, mode) {
    if (mode === "upper") return value.toLocaleUpperCase();
    if (mode === "lower") return value.toLocaleLowerCase();
    if (mode === "title") return value.toLocaleLowerCase().replace(/[\p{L}\p{M}\p{N}]+(?:['’][\p{L}\p{M}\p{N}]+)*/gu,
        word=>word.replace(/\p{L}/u,letter=>letter.toLocaleUpperCase()));
    if (mode === "sentence") return value.toLocaleLowerCase().replace(/(^|[.!?]\s+)(\p{L})/gu,(_,prefix,c)=>prefix+c.toLocaleUpperCase());
    return value;
}

function graphicFrames(stage, box, style, action) {
    const direction = style.direction || "right";
    const offsets = {right:`${stage.clientWidth-box.offsetLeft}px,0`,left:`-${box.offsetLeft+box.offsetWidth}px,0`,
        up:`0,-${box.offsetTop+box.offsetHeight}px`,down:`0,${stage.clientHeight-box.offsetTop}px`};
    const wipes = {right:"0 0 0 100%",left:"0 100% 0 0",up:"100% 0 0 0",down:"0 0 100% 0"};
    let frames;
    if (style.animation === "fade") frames = [{opacity:0},{opacity:1}];
    else if (style.animation === "wipe") frames = [{clipPath:`inset(${wipes[direction]})`},{clipPath:"inset(0)"}];
    else frames = [{transform:`translate(${offsets[direction]})`},{transform:"translate(0,0)"}];
    return action === "hide" ? frames.reverse() : frames;
}

function graphicsRenderer(stage) {
    let current, untilNextClock, signature, generation = 0, animations = [];

    function fit(element, font, lines, available=Infinity) {
        element.style.setProperty("-webkit-line-clamp","unset");
        const fits = size => {
            element.style.fontSize=size+"px";
            return element.scrollHeight<=Math.min(available,size*1.12*lines+1) && element.scrollWidth<=element.clientWidth+1;
        };
        if (font>0 && !fits(font)) {
            let low=Math.min(font,1), high=font;
            while (high-low>.25) {
                const middle=(low+high)/2;
                if (fits(middle)) low=middle; else high=middle;
            }
            element.style.fontSize=low+"px";
        }
        element.style.removeProperty("-webkit-line-clamp");
    }

    function makeCrawler(content, item, style, ratio, fitWidth) {
        const track=document.createElement("div"), unit=document.createElement("span");
        track.className="crawl"; unit.className="crawl-unit";
        for (const part of item.parts || [item.text || ""]) {
            const label=document.createElement("span"), separator=document.createElement("span");
            label.textContent=graphicsTextCase(part,style.text_case);
            separator.className="crawl-separator";
            if (style.separator === "logo" && style.logo) {
                const img=document.createElement("img"); img.alt=""; img.src=style.logo; separator.append(img);
            } else if (style.separator !== "space") separator.textContent="•";
            unit.append(label,separator);
        }
        track.append(unit); content.append(track);
        const size = () => {
            const step=Math.max(1,unit.getBoundingClientRect().width);
            fitWidth?.(step);
            for (const clone of [...track.children].slice(1)) clone.remove();
            const copies=Math.min(256,Math.ceil(content.clientWidth/step)+2);
            while (track.childElementCount<copies) track.append(unit.cloneNode(true));
            track.style.setProperty("--distance",-step+"px");
            track.style.setProperty("--duration",step/(style.speed*ratio)+"s");
        };
        const image = unit.querySelector("img");
        if (image && !image.complete) image.addEventListener("load",size,{once:true});
        size();
    }

    function positionBox(box, style, compact, slot) {
        if (style.background_size === "fill") return;
        const {horizontal,vertical} = style;
        const legacyX = slot === "right" ? style.right : style.x;
        const remainingX = Math.max(0,stage.clientWidth-box.offsetWidth);
        const remainingY = Math.max(0,stage.clientHeight-box.offsetHeight);
        const x = {left:0,center:remainingX/2,right:remainingX};
        const y = {top:0,middle:remainingY/2,bottom:remainingY};
        box.style.left=(x[horizontal] ?? (compact ? 0 : Math.min(remainingX,stage.clientWidth*legacyX/100)))+"px";
        box.style.top=(y[vertical] ?? (compact ? 0 : Math.min(remainingY,stage.clientHeight*style.y/100)))+"px";
    }

    function draw() {
        clearInterval(untilNextClock);
        stage.replaceChildren();
        if (!current || !stage.clientWidth) return;
        const {kind,items,compact}=current;
        const reference=compact ? graphicsSizes[kind][0] : 1920;
        const ratio=stage.clientWidth/reference;
        const dateOnly=kind === "date";
        for (const [slot,item] of Object.entries(items)) {
            const style=graphicsItemStyle(kind,current.style,item);
            const legacyClock=kind === "clock" && !compact;
            if (legacyClock && !style.show_time && !style.show_date) continue;
            const box=document.createElement("div"), content=document.createElement("div");
            box.className="graphic"; content.className="graphic-content"; box.append(content);
            const legacyWidth=style.horizontal==="existing" ? Math.min(style.width,100-(slot==="right" ? style.right : style.x)) : style.width;
            const width=style.manual_width ?? (compact ? 100 : legacyWidth);
            if (style.background_size === "manual" && !width) continue;
            const opacity=Math.round((style.opacity??100)*255/100).toString(16).padStart(2,"0");
            const background=style.transparent ? "transparent" : style.background+opacity;
            const corners=style.corners === "individual" ? [style.radius_tl,style.radius_tr,style.radius_br,style.radius_bl] : [style.radius];
            const filling=style.background_size === "fill", fitting=style.background_size === "fit";
            const band=style.description_layout==="band" && item.show_description && item.description?.trim();
            const [top,right,bottom,left]=["top","right","bottom","left"].map(side=>
                (style.padding_mode==="sides" ? style["padding_"+side] : style.padding)*ratio);
            const fixedHeight=kind==="headlines"
                ? stage.clientHeight*(style.headline_height ?? (compact ? 100 : Math.min(100,100*(style.font*ratio*style.lines*1.12+top+bottom)/stage.clientHeight)))/100
                : null;
            const areaHeight=filling ? stage.clientHeight : fixedHeight ?? stage.clientHeight;
            const areaWidth=filling || fitting ? stage.clientWidth : stage.clientWidth*width/100;
            const scaleY=Math.min(1, (band ? .65 : .9)*areaHeight/Math.max((top+bottom)*(band ? 1.5 : 1),1));
            const scaleX=Math.min(1, .9*areaWidth/Math.max(left+right,1));
            const pad=[top*scaleY,right*scaleX,bottom*scaleY,left*scaleX];
            const bandPad=pad.map((value,index)=>index%2 ? value : value/2);
            const textAlignment={top:"flex-start",middle:"center",bottom:"flex-end"}[style.text_vertical];
            Object.assign(box.style,{left:"0",top:"0",width:filling ? "100%" : fitting ? "max-content" : width+"%",
                height:filling ? "100%" : fixedHeight===null ? "auto" : fixedHeight+"px",maxWidth:"100%",maxHeight:"100%",
                color:style.foreground,background:band ? "transparent" : background,
                borderRadius:corners.map(radius=>(radius??style.radius)*ratio+"px").join(" "),
                padding:band ? "0" : pad.map(value=>value+"px").join(" "),
                justifyContent:band ? "flex-end" : textAlignment,
                textAlign:style.align,fontFamily:JSON.stringify(style.family)+", Arial, sans-serif",fontSize:style.font*ratio+"px",
                fontWeight:style.bold?"700":"400"});
            const lines = kind === "headlines" ? style.lines : kind === "clock" ? 1 : Infinity;
            if (Number.isFinite(lines)) box.style.setProperty("--lines",lines);
            stage.append(box);
            const position = () => positionBox(box,style,compact,slot);
            const available = Math.max(1,areaHeight-pad[0]-pad[2]-(band ? bandPad[0]+bandPad[2] : 0));
            if (kind === "crawlers") {
                box.style.fontSize=Math.min(style.font*ratio,available/1.12)+"px";
                makeCrawler(content,item,style,ratio,fitting ? step=>{box.style.width=step+pad[1]+pad[3]+"px"; position();} : null);
            } else {
                const title=document.createElement("div"), subtitle=document.createElement("div");
                title.className="title"; subtitle.className="subtitle"; subtitle.style.color=style.secondary;
                content.append(title);
                if (band) {
                    const strip=document.createElement("div");
                    strip.className="description-band";
                    strip.style.padding=bandPad.map(value=>value+"px").join(" ");
                    if (!style.description_transparent) strip.style.backgroundColor=style.description_background;
                    content.classList.add("graphic-band-title");
                    Object.assign(content.style,{background,padding:pad.map(value=>value+"px").join(" "),justifyContent:textAlignment});
                    strip.append(subtitle);
                    box.append(strip);
                } else {
                    if (style.description_background && !style.description_transparent) {
                        subtitle.classList.add("subtitle-background");
                        subtitle.dataset.align=style.align;
                        subtitle.style.backgroundColor=style.description_background;
                    }
                    content.append(subtitle);
                }
                if (kind === "clock" || dateOnly) {
                    if (!dateOnly) title.classList.add("single");
                    if (legacyClock) title.hidden=!style.show_time;
                    subtitle.hidden=!legacyClock || !style.show_date;
                    const tick=()=>{
                        const stamp=formatGraphicsClock(new Date(),style.time_format || "12hms",style.date_format);
                        const value=graphicsTextCase(dateOnly ? stamp.date : stamp.time,style.text_case);
                        const description=legacyClock ? graphicsTextCase(stamp.date,style.text_case) : "";
                        if (title.textContent===value && subtitle.textContent===description) return;
                        title.textContent=value; subtitle.textContent=description;
                        const descriptionSize=(style.description_font ?? style.font*.54)*ratio;
                        subtitle.style.fontSize=descriptionSize+"px";
                        if (!title.hidden) fit(title,style.font*ratio,lines,available-(subtitle.hidden ? 0 : descriptionSize*1.4));
                        position();
                    };
                    tick();
                    untilNextClock=setInterval(tick,!dateOnly && style.time_format.endsWith("hmsms") ? 33 : 250);
                } else {
                    title.textContent=graphicsTextCase(item.text,style.text_case);
                    if (item.show_description) subtitle.textContent=graphicsTextCase(item.description || "",style.text_case);
                    const subtitleSize=subtitle.textContent ? Math.min((style.description_font ?? style.font*.54)*ratio,available*(band ? .4 : .6)) : 0;
                    if (subtitleSize) subtitle.style.fontSize=subtitleSize+"px";
                    if (band) {
                        fit(subtitle,subtitleSize,1,available*.5);
                        fit(title,style.font*ratio,lines,Math.max(1,available-subtitle.offsetHeight));
                    } else {
                        fit(title,style.font*ratio,lines,available-subtitleSize*1.4);
                        if (subtitleSize) fit(subtitle,subtitleSize,1,Math.max(1,available-title.offsetHeight-subtitleSize*.25));
                    }
                }
            }
            position();
        }
    }

    new ResizeObserver(draw).observe(stage);
    return (frame, action) => {
        const next=JSON.stringify(frame);
        if (next===signature && !action) return;
        const ticket=++generation;
        animations.forEach(animation=>animation.cancel()); animations=[];
        signature=next;
        const animatedFrame=action==="hide" ? current : frame;
        const style=animatedFrame && graphicsItemStyle(animatedFrame.kind,animatedFrame.style,animatedFrame.items.main || {});
        current=frame;
        if (action === "hide" && style?.animation !== "cut" && stage.children.length) {
            animations=[...stage.children].map(node=>node.animate(graphicFrames(stage,node,style,action),{duration:style.duration,fill:"both",easing:"ease-in-out"}));
            Promise.allSettled(animations.map(animation=>animation.finished)).then(()=>{if (generation===ticket) draw();});
            return;
        }
        draw();
        if (action === "show" && style?.animation !== "cut") animations=[...stage.children].map(node=>
            node.animate(graphicFrames(stage,node,style,action),{duration:style.duration,easing:"ease-in-out"}));
    };
}
