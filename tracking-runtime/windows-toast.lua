local ffi = require("ffi")

ffi.cdef[[
int MultiByteToWideChar(unsigned int code_page, unsigned long flags,
    const char *input, int size, wchar_t *output, int capacity);
intptr_t ShellExecuteW(void *window, const wchar_t *operation, const wchar_t *file,
    const wchar_t *parameters, const wchar_t *directory, int show);
]]

local kernel = ffi.load("kernel32")
local shell = ffi.load("shell32")

local function wide(value)
    local size = kernel.MultiByteToWideChar(65001, 0, value, -1, nil, 0)
    local result = ffi.new("wchar_t[?]", size)
    kernel.MultiByteToWideChar(65001, 0, value, -1, result, size)
    return result
end

return function(runtime, status)
    local python = runtime .. "../.venv/Scripts/pythonw.exe"
    local candidate = io.open(python, "rb")
    if not candidate then return end
    candidate:close()
    local args = '"' .. runtime .. 'hotkey-toast.py" ' .. status
    shell.ShellExecuteW(nil, nil, wide(python:gsub("/", "\\")), wide(args), nil, 0)
end
