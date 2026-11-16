local obs = obslua
local ffi = require("ffi")
local windows = ffi.os == "Windows"
local libobs = windows and ffi.load("obs") or
    ffi.load("/Applications/OBS.app/Contents/Frameworks/libobs.framework/Versions/A/libobs")
ffi.cdef[[
void obs_hotkey_enable_background_press(bool enable);
bool CGEventSourceKeyState(int state, unsigned short key);
void *objc_getClass(const char *name);
void *sel_registerName(const char *name);
void *objc_msgSend(void *receiver, void *selector, ...);
short GetAsyncKeyState(int key);
void *GetForegroundWindow(void);
unsigned long GetWindowThreadProcessId(void *window, unsigned long *pid);
unsigned long GetCurrentProcessId(void);
struct os_process_args *os_process_args_create(const char *executable);
void os_process_args_add_arg(struct os_process_args *args, const char *arg);
void os_process_args_destroy(struct os_process_args *args);
struct os_process_pipe *os_process_pipe_create2(const struct os_process_args *args, const char *type);
int os_process_pipe_destroy(struct os_process_pipe *pipe);
]]

local key, is_active
if windows then
    local user = ffi.load("user32")
    local kernel = ffi.load("kernel32")
    local pid = ffi.new("unsigned long[1]")
    local own_pid = kernel.GetCurrentProcessId()
    local virtual_keys = {
        [0]=65, [1]=83, [2]=68, [3]=70, [8]=67, [10]=226, [12]=81,
        [13]=87, [14]=69, [18]=49, [19]=50, [50]=192, [54]=92, [55]=91,
        [56]=160, [60]=161, [58]=164, [61]=165, [59]=162, [62]=163,
    }
    key = function(code) return user.GetAsyncKeyState(virtual_keys[code]) < 0 end
    is_active = function()
        pid[0] = 0
        user.GetWindowThreadProcessId(user.GetForegroundWindow(), pid)
        return pid[0] == own_pid
    end
else
    local cg = ffi.load("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    local objc = ffi.load("/usr/lib/libobjc.A.dylib")
    local app = objc.objc_msgSend(objc.objc_getClass("NSApplication"), objc.sel_registerName("sharedApplication"))
    local selector = objc.sel_registerName("isActive")
    local send_bool = ffi.cast("bool (*)(void *, void *)", objc.objc_msgSend)
    key = function(code) return cg.CGEventSourceKeyState(1, code) end
    is_active = function() return send_bool(app, selector) end
end

local paused, was_down = false, false
local toggle_id
local debounce = 0
local toolkit_obs_config = ""
local toolkit_rundown_data = ""

local function runtime(file)
    return script_path() .. "../tracking-runtime/" .. file
end

local function quote(path)
    return "'" .. path:gsub("'", "'\\''") .. "'"
end

local windows_toast
local function toast(status)
    if windows then
        windows_toast = windows_toast or dofile(runtime("windows-toast.lua"))
        windows_toast(runtime(""), status)
        return
    end
    os.execute(quote(runtime("tracking-toast")) .. " " .. status .. " </dev/null >/dev/null 2>&1 &")
end

local function publish_state()
    local path = runtime("hotkey-dock.state")
    local file = io.open(path .. ".tmp", "w")
    if not file then return end
    file:write(paused and "off" or "on")
    file:close()
    if windows then os.remove(path) end
    os.rename(path .. ".tmp", path)
end

local function set_paused(value)
    paused = value
    libobs.obs_hotkey_enable_background_press(not paused)
    obs.script_log(obs.LOG_INFO, paused and "OBS hotkeys paused" or "OBS hotkeys resumed")
    publish_state()
    toast(paused and "PAUSED" or "RESUMED")
end

local dock_server

local function save_rundown_source(data)
    local source = obs.calldata_source(data, "source")
    if source == nil or obs.obs_source_get_name(source) ~= "Rundown Player"
        or obs.obs_source_get_id(source) ~= "ffmpeg_source" then return end
    local settings = obs.obs_source_get_settings(source)
    if obs.obs_data_get_bool(settings, "obs_controls_toolkit_rundown")
        and obs.obs_data_has_user_value(settings, "local_file") then
        -- Default values stay available to the decoder but are omitted from the scene collection JSON.
        local path = obs.obs_data_get_string(settings, "local_file")
        obs.obs_data_set_default_string(settings, "local_file", path)
        obs.obs_data_unset_user_value(settings, "local_file")
    end
    obs.obs_data_release(settings)
end

local function start_docks()
    local python = script_path() .. "../.venv/" .. (windows and "Scripts/python.exe" or "bin/python")
    local candidate = io.open(python, "rb")
    if not candidate then
        obs.script_log(obs.LOG_WARNING, "Run OBS Control Toolkit Setup to enable the docks.")
        return
    end
    candidate:close()
    local args = libobs.os_process_args_create(python)
    libobs.os_process_args_add_arg(args, "-B")
    libobs.os_process_args_add_arg(args, runtime("toolkit_host.py"))
    libobs.os_process_args_add_arg(args, toolkit_obs_config)
    libobs.os_process_args_add_arg(args, toolkit_rundown_data)
    dock_server = libobs.os_process_pipe_create2(args, "w")
    libobs.os_process_args_destroy(args)
    if dock_server == nil then
        obs.script_log(obs.LOG_ERROR, "Could not start the toolkit docks. Run Setup again.")
    end
end

local movement = {0, 1, 2, 12, 13, 14} -- A, S, D, Q, W, E
local previous, repeats, held = {}, {}, {}
local tick, next_reminder = 0, 0
local combo_down = false

local function check_reminder(active)
    tick = tick + 1
    if not paused or not active then
        previous, repeats, held = {}, {}, {}
        combo_down = false
        return
    end
    local shift = key(56) or key(60)
    local command = key(55) or key(54)
    local control = key(59) or key(62)
    local option = key(58) or key(61)
    local combo = not option and (
        (shift and not command and not control and (key(8) or key(3))) or
        ((windows and control or command) and not shift and key(18)))
    local reminder = combo and not combo_down
    combo_down = combo
    for _, code in ipairs(movement) do
        local down = not shift and not command and not control and not option and key(code)
        if down and not previous[code] then
            local recent = repeats[code] or {}
            while recent[1] and tick - recent[1] > 25 do table.remove(recent, 1) end
            recent[#recent + 1] = tick
            repeats[code] = recent
            held[code] = tick
            if #recent >= 3 then reminder = true end
        elseif down and tick - held[code] == 12 then
            reminder = true
        end
        previous[code] = down
    end
    if reminder and tick >= next_reminder then
        next_reminder = tick + 115
        obs.script_log(obs.LOG_INFO, "Showing paused controls reminder")
        toast("REMINDER")
    end
end

local movement_was_down = false
local next_tracking_hint = 0

local movement_hint_id
local function show_tracking_hint()
    if paused or tick < next_tracking_hint then return end
    local file = io.open(runtime("tracking-active.state"), "r")
    if not file then return end
    local tracking = file:read("*a") == "on"
    file:close()
    if not tracking then return end
    next_tracking_hint = tick + 115
    obs.script_log(obs.LOG_INFO, "Showing manual camera controls reminder")
    toast("MANUAL_LOCKED")
end

local function check_tracking_hint(active)
    local down = false
    if active and not paused and not (
        key(54) or key(55) or key(56) or key(60) or
        key(58) or key(61) or key(59) or key(62)) then
        for _, code in ipairs(movement) do
            if key(code) then down = true; break end
        end
    end
    if down and not movement_was_down and tick >= next_tracking_hint then
        show_tracking_hint()
    end
    movement_was_down = down
end

local function toggle()
    if debounce > 0 then return end
    debounce = 8
    set_paused(not paused)
end

local function check_toggle()
    if debounce > 0 then debounce = debounce - 1 end
    -- The physical backtick/tilde key is 50 on the Mac ANSI layout.
    local modifier = windows and (key(59) or key(62)) or
        (not windows and (key(54) or key(55)))
    local down = (key(50) or key(10)) and modifier
    local active = is_active()
    if down and not was_down and active then
        toggle()
    end
    was_down = down
    if dock_server and os.remove(runtime("hotkey-dock.toggle")) then toggle() end
    check_reminder(active)
    check_tracking_hint(active)
    if paused then libobs.obs_hotkey_enable_background_press(false) end
end

function script_description()
    return "Press " .. (windows and "Ctrl" or "Command") .. " + backtick (the tilde key) to pause or resume OBS shortcuts."
end

function script_properties()
    local p = obs.obs_properties_create()
    obs.obs_properties_add_button(p, "toggle", "Pause / resume hotkeys", function()
        set_paused(not paused)
        return false
    end)
    return p
end

function script_load(settings)
    toolkit_obs_config = obs.obs_data_get_string(settings, "toolkit_obs_config")
    toolkit_rundown_data = obs.obs_data_get_string(settings, "toolkit_rundown_data")
    toggle_id = obs.obs_hotkey_register_frontend("obs_pause_shortcuts", "Pause / resume OBS hotkeys", function(pressed)
        if pressed then toggle() end
    end)
    local bindings = obs.obs_data_array_create()
    local binding = obs.obs_data_create()
    obs.obs_data_set_bool(binding, windows and "control" or "command", true)
    obs.obs_data_set_string(binding, "key", "OBS_KEY_QUOTELEFT")
    obs.obs_data_array_push_back(bindings, binding)
    obs.obs_hotkey_load(toggle_id, bindings)
    obs.obs_data_release(binding)
    obs.obs_data_array_release(bindings)
    movement_hint_id = obs.obs_hotkey_register_frontend(
        "fomako_manual_tracking_hint", "FoMaKo: Manual controls reminder",
        function(pressed) if pressed then show_tracking_hint() end end)
    local movement_bindings = obs.obs_data_array_create()
    for _, letter in ipairs({"W", "A", "S", "D", "Q", "E"}) do
        local item = obs.obs_data_create()
        obs.obs_data_set_string(item, "key", "OBS_KEY_" .. letter)
        obs.obs_data_array_push_back(movement_bindings, item)
        obs.obs_data_release(item)
    end
    obs.obs_hotkey_load(movement_hint_id, movement_bindings)
    obs.obs_data_array_release(movement_bindings)
    os.remove(runtime("hotkey-dock.toggle"))
    publish_state()
    obs.signal_handler_connect(obs.obs_get_signal_handler(), "source_save", save_rundown_source)
    start_docks()
    obs.timer_add(check_toggle, 35)
end

function script_unload()
    obs.timer_remove(check_toggle)
    obs.signal_handler_disconnect(obs.obs_get_signal_handler(), "source_save", save_rundown_source)
    if dock_server then
        libobs.os_process_pipe_destroy(dock_server)
        dock_server = nil
    end
    os.remove(runtime("hotkey-dock.state"))
    if toggle_id then obs.obs_hotkey_unregister(toggle_id) end
    if movement_hint_id then obs.obs_hotkey_unregister(movement_hint_id) end
    if paused then libobs.obs_hotkey_enable_background_press(true) end
end
