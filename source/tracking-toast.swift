import AppKit

guard CommandLine.arguments.count == 2,
      ["ON", "OFF", "PAUSED", "RESUMED", "REMINDER", "MANUAL_LOCKED"].contains(CommandLine.arguments[1]),
      let screen = NSScreen.screens.first(where: { $0.frame.contains(NSEvent.mouseLocation) }) ?? NSScreen.main
else { exit(2) }

let status = CommandLine.arguments[1]
let enabled = status == "ON" || status == "RESUMED"
let manualLocked = status == "MANUAL_LOCKED"
let hotkeys = status == "PAUSED" || status == "RESUMED" || status == "REMINDER"
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let frame = screen.visibleFrame
let width: CGFloat = manualLocked ? 360 : 296
let height: CGFloat = 76
let panel = NSPanel(
    contentRect: NSRect(x: frame.midX - width / 2, y: frame.minY + 28, width: width, height: height),
    styleMask: [.borderless, .nonactivatingPanel],
    backing: .buffered,
    defer: false
)
panel.isOpaque = false
panel.backgroundColor = .clear
panel.hasShadow = true
panel.ignoresMouseEvents = true
panel.hidesOnDeactivate = false
panel.level = .statusBar
panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]

let body = NSView(frame: NSRect(x: 0, y: 0, width: width, height: height))
body.wantsLayer = true
body.layer?.cornerRadius = 24
body.layer?.backgroundColor = NSColor(srgbRed: 0.09, green: 0.11, blue: 0.14, alpha: 0.98).cgColor
let tint = enabled ? NSColor(srgbRed: 0.42, green: 0.87, blue: 0.61, alpha: 1) :
                     NSColor(srgbRed: 0.98, green: 0.73, blue: 0.40, alpha: 1)
let icon = NSTextField(labelWithString: enabled ? "✓" : "–")
icon.font = .systemFont(ofSize: 20, weight: .bold)
icon.textColor = tint
icon.alignment = .center
icon.frame = NSRect(x: 15, y: 23, width: 30, height: 29)
body.addSubview(icon)
let title = NSTextField(labelWithString: manualLocked ? "Auto tracking is on" : hotkeys ? (enabled ? "OBS controls on" : "OBS controls off") : (enabled ? "Auto tracking is on" : "Auto tracking is off"))
title.font = .systemFont(ofSize: 16, weight: .semibold)
title.textColor = .white
title.frame = NSRect(x: 55, y: 39, width: width - 71, height: 22)
body.addSubview(title)
let subtitle = NSTextField(labelWithString: manualLocked ? "Press ⌘1 to use manual camera controls" : hotkeys ? (enabled ? "Camera and scene shortcuts are active" : "Press Command + ` to resume") : "Confirmed by the camera")
subtitle.font = .systemFont(ofSize: 12, weight: .regular)
subtitle.textColor = NSColor(white: 0.77, alpha: 1)
subtitle.frame = NSRect(x: 55, y: 18, width: width - 71, height: 17)
body.addSubview(subtitle)
panel.contentView = body
panel.orderFrontRegardless()
DispatchQueue.main.asyncAfter(deadline: .now() + 1.7) {
    NSAnimationContext.runAnimationGroup({ context in
        context.duration = 0.2
        panel.animator().alphaValue = 0
    }, completionHandler: {
        app.stop(nil)
        exit(0)
    })
}
app.run()
