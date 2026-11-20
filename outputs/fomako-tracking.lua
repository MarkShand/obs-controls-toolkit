local obs = obslua
local ffi = require("ffi")
local windows = ffi.os == "Windows"
local defaults = {
    camera_ip = "127.0.0.1",
    camera_port = 5678,
    visca_address = 129,
    command_on = "0A 01 32 00 00 02 00",
    command_off = "0A 01 32 00 00 03 00",
    show_tracking_toast = true,
}
local target, port, address = defaults.camera_ip, defaults.camera_port, defaults.visca_address
local command_on, command_off = defaults.command_on, defaults.command_off
local show_tracking_toast = defaults.show_tracking_toast
local pending
local toggle_hotkey
local tracking_enabled = false

local function save_setup()
    obs.timer_remove(save_setup)
    obs.obs_frontend_save()
end

ffi.cdef[[
typedef struct {
    unsigned char length, family;
    unsigned short port;
    unsigned int address;
    unsigned char padding[8];
} fomako_sockaddr_in;
int socket(int domain, int type, int protocol);
int connect(int fd, const void *address, unsigned int length);
int close(int fd);
long send(int fd, const void *data, unsigned long len, int flags);
long recv(int fd, void *data, unsigned long len, int flags);
unsigned short htons(unsigned short value);
int inet_pton(int family, const char *src, void *dst);
typedef bool (*fomako_hotkey_enum)(void *, size_t, void *);
void obs_enum_hotkeys(fomako_hotkey_enum callback, void *data);
const char *obs_hotkey_get_name(const void *hotkey);
void obs_hotkey_load(size_t id, void *bindings);
]]
local net = ffi.C
local libobs = windows and ffi.load("obs") or ffi.load("/Applications/OBS.app/Contents/Frameworks/libobs.framework/Versions/A/libobs")
local msg_dontwait = 0x80 -- Darwin
local eagain = 35 -- Darwin
local socket_error = ffi.errno
if windows then
    local winsock = ffi.load("ws2_32")
    -- Distinct FFI declarations preserve the pointer-sized Windows SOCKET.
    ffi.cdef[[
    typedef struct { unsigned short family, port; unsigned int address; unsigned char padding[8]; } fomako_win_addr;
    int WSAGetLastError(void);
    int WSAStartup(unsigned short version, void *data);
    int WSACleanup(void);
    int closesocket(uintptr_t socket);
    int ioctlsocket(uintptr_t socket, long command, unsigned long *value);
    int InetPtonA(int family, const char *src, void *dst);
    ]]
    local socket_fn = ffi.cast("uintptr_t (*)(int, int, int)", winsock.socket)
    local connect_fn = ffi.cast("int (*)(uintptr_t, const void *, int)", winsock.connect)
    local send_fn = ffi.cast("int (*)(uintptr_t, const void *, int, int)", winsock.send)
    local recv_fn = ffi.cast("int (*)(uintptr_t, void *, int, int)", winsock.recv)
    local data = ffi.new("uint64_t[64]")
    assert(winsock.WSAStartup(0x0202, data) == 0, "Could not initialize Winsock")
    local invalid = ffi.cast("uintptr_t", -1)
    net = {
        socket = function(family, kind, protocol)
            local fd = socket_fn(family, kind, protocol)
            if fd == invalid then return -1 end
            local enabled = ffi.new("unsigned long[1]", 1)
            if winsock.ioctlsocket(fd, 0x8004667e, enabled) ~= 0 then
                winsock.closesocket(fd)
                return -1
            end
            return fd
        end,
        connect = connect_fn, send = send_fn, recv = recv_fn,
        close = winsock.closesocket, htons = winsock.htons, inet_pton = winsock.InetPtonA,
        cleanup = winsock.WSACleanup,
    }
    socket_error = winsock.WSAGetLastError
    msg_dontwait, eagain = 0, 10035
end
local function runtime()
    return script_path() .. "../tracking-runtime/"
end

local function publish_tracking_state()
    local path = runtime() .. "tracking-active.state"
    local file = io.open(path .. ".tmp", "w")
    if not file then return end
    file:write(tracking_enabled and "on" or "off")
    file:close()
    if windows then os.remove(path) end
    os.rename(path .. ".tmp", path)
end

local function quote(s)
    return "'" .. s:gsub("'", "'\\''") .. "'"
end

local function log(level, message)
    obs.script_log(level, "FoMaKo Camera 1: " .. message)
end

local function show_confirmation(label)
    if not show_tracking_toast then return end
    if windows then
        os.execute('start "" /b pythonw "' .. runtime() .. 'hotkey-toast.py" ' .. label)
        return
    end
    local executable = runtime() .. "tracking-toast"
    local helper = io.open(executable, "rb")
    if not helper then
        log(obs.LOG_WARNING, "Tracking popup helper is missing.")
        return
    end
    helper:close()
    os.execute(quote(executable) .. " " .. (label == "ON" and "ON" or "OFF") .. " </dev/null >/dev/null 2>&1 &")
end

local poll
local function stop_pending()
    if pending then
        net.close(pending.fd)
        pending = nil
        obs.timer_remove(poll)
    end
end

poll = function()
    local req = pending
    if not req then return end
    local buf = ffi.new("unsigned char[64]")
    for _ = 1, 8 do
        local n = tonumber(net.recv(req.fd, buf, 64, msg_dontwait))
        if n < 0 then
            local err = socket_error()
            if err ~= eagain and err ~= 4 then
                log(obs.LOG_WARNING, "Could not read camera reply (errno " .. err .. ").")
                stop_pending()
                return
            end
            break
        end
        for i = 0, n - 2 do
            if buf[i] == req.reply_address then
                local kind = bit.band(buf[i + 1], 0xF0)
                if kind == 0x50 then
                    tracking_enabled = req.label == "ON"
                    publish_tracking_state()
                    log(obs.LOG_INFO, "Camera confirmed auto tracking " .. req.label .. ".")
                    stop_pending()
                    show_confirmation(req.label)
                    return
                elseif kind == 0x60 then
                    log(obs.LOG_WARNING, string.format("Camera rejected tracking %s (VISCA error 0x%02X).", req.label, buf[i + 2] or 0))
                    stop_pending()
                    return
                end
            end
        end
    end
    req.ticks = req.ticks + 1
    if req.ticks >= 40 then
        log(obs.LOG_WARNING, "No completion reply for tracking " .. req.label .. ".")
        stop_pending()
    end
end

local function make_payload(command)
    local bytes = {string.char(address)}
    for part in command:gmatch("%S+") do
        if not part:match("^%x%x$") then return nil end
        local byte = tonumber(part, 16)
        if byte == 0xFF or #bytes >= 15 then return nil end
        bytes[#bytes + 1] = string.char(byte)
    end
    if #bytes == 1 then return nil end
    bytes[#bytes + 1] = string.char(0xFF)
    return table.concat(bytes)
end

local function make_addr(ip, udp_port)
    local addr = ffi.new(windows and "fomako_win_addr[1]" or "fomako_sockaddr_in[1]")
    if not windows then addr[0].length = ffi.sizeof(addr[0]) end
    addr[0].family = 2 -- AF_INET
    addr[0].port = net.htons(udp_port)
    if net.inet_pton(2, ip, ffi.cast("unsigned char *", addr) + 4) ~= 1 then
        log(obs.LOG_WARNING, "Invalid camera IP.")
        return
    end
    return addr
end

local function track(on)
    if pending then return end
    local payload = make_payload(on and command_on or command_off)
    if not payload then
        log(obs.LOG_WARNING, "Enter space-separated hex bytes without the address or trailing FF.")
        return
    end
    local addr = make_addr(target, port)
    if not addr then return end
    local fd = net.socket(2, 2, 0) -- AF_INET, SOCK_DGRAM
    if fd < 0 then
        log(obs.LOG_WARNING, "Could not open the camera connection (errno " .. socket_error() .. ").")
        return
    end
    if net.connect(fd, addr, ffi.sizeof(addr[0])) ~= 0 or net.send(fd, payload, #payload, msg_dontwait) ~= #payload then
        local err = socket_error()
        net.close(fd)
        log(obs.LOG_WARNING, "Could not send the command to the camera (errno " .. err .. ").")
        return
    end
    pending = {fd = fd, label = on and "ON" or "OFF", ticks = 0, reply_address = (address - 0x80 + 8) * 16}
    obs.timer_add(poll, 50)
end

function script_description()
    return "Camera auto tracking over VISCA UDP. Use Command+1 to toggle. The first press enables tracking after a reload; later presses use the last camera-confirmed state. Enter command bytes without the camera address or trailing FF. See Script Log for camera replies and Settings → Hotkeys for shortcuts."
end

function script_properties()
    local p = obs.obs_properties_create()
    obs.obs_properties_add_button(p, "fomako_tracking_on", "Tracking On", function() track(true); return false end)
    obs.obs_properties_add_button(p, "fomako_tracking_off", "Tracking Off", function() track(false); return false end)
    obs.obs_properties_add_text(p, "camera_ip", "Camera IPv4 address", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_int(p, "camera_port", "VISCA UDP port", 1, 65535, 1)
    obs.obs_properties_add_int(p, "visca_address", "VISCA address (decimal)", 129, 135, 1)
    obs.obs_properties_add_text(p, "command_on", "Tracking On hex bytes", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_text(p, "command_off", "Tracking Off hex bytes", obs.OBS_TEXT_DEFAULT)
    obs.obs_properties_add_bool(p, "show_tracking_toast", "Show tracking popup")
    return p
end

function script_defaults(settings)
    for key, value in pairs(defaults) do
        if type(value) == "boolean" then
            obs.obs_data_set_default_bool(settings, key, value)
        elseif type(value) == "number" then
            obs.obs_data_set_default_int(settings, key, value)
        else
            obs.obs_data_set_default_string(settings, key, value)
        end
    end
end

function script_update(settings)
    local next_target = obs.obs_data_get_string(settings, "camera_ip"):match("^%s*(.-)%s*$")
    local next_port = obs.obs_data_get_int(settings, "camera_port")
    local next_address = obs.obs_data_get_int(settings, "visca_address")
    if target ~= next_target or port ~= next_port or address ~= next_address then
        stop_pending()
        tracking_enabled = false
        publish_tracking_state()
    end
    target, port, address = next_target, next_port, next_address
    command_on = obs.obs_data_get_string(settings, "command_on")
    command_off = obs.obs_data_get_string(settings, "command_off")
    show_tracking_toast = obs.obs_data_get_bool(settings, "show_tracking_toast")
end

local function clear_legacy_shortcuts()
    obs.timer_remove(clear_legacy_shortcuts)
    local ids = {}
    local collect = ffi.cast("fomako_hotkey_enum", function(_, id, hotkey)
        local name = ffi.string(libobs.obs_hotkey_get_name(hotkey))
        if name == "ml_ptz_at_on_active" or name == "ml_ptz_at_off_active" then
            ids[#ids + 1] = id
        end
        return true
    end)
    libobs.obs_enum_hotkeys(collect, nil)
    collect:free()
    for _, id in ipairs(ids) do
        libobs.obs_hotkey_load(id, nil)
    end
    obs.timer_add(save_setup, 350)
end

function script_load(settings)
    publish_tracking_state()
    toggle_hotkey = obs.obs_hotkey_register_frontend(
        "fomako_tracking_toggle", "FoMaKo Camera 1: Toggle Tracking", function(pressed)
            if pressed then track(not tracking_enabled) end
        end)
    local bindings
    if obs.obs_data_has_user_value(settings, "fomako_tracking_toggle") then
        bindings = obs.obs_data_get_array(settings, "fomako_tracking_toggle")
    else
        bindings = obs.obs_data_array_create()
        local binding = obs.obs_data_create()
        obs.obs_data_set_bool(binding, windows and "control" or "command", true)
        obs.obs_data_set_string(binding, "key", "OBS_KEY_1")
        obs.obs_data_array_push_back(bindings, binding)
        obs.obs_data_release(binding)
    end
    obs.obs_hotkey_load(toggle_hotkey, bindings)
    obs.obs_data_array_release(bindings)
    obs.timer_add(clear_legacy_shortcuts, 500)
end

function script_save(settings)
    obs.obs_data_unset_user_value(settings, "fomako_tracking_on")
    obs.obs_data_unset_user_value(settings, "fomako_tracking_off")
    local bindings = obs.obs_hotkey_save(toggle_hotkey)
    obs.obs_data_set_array(settings, "fomako_tracking_toggle", bindings)
    obs.obs_data_array_release(bindings)
end

function script_unload()
    os.remove(runtime() .. "tracking-active.state")
    stop_pending()
    obs.timer_remove(save_setup)
    obs.timer_remove(clear_legacy_shortcuts)
    if toggle_hotkey then obs.obs_hotkey_unregister(toggle_hotkey) end
    if windows then net.cleanup() end
end
