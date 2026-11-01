// SPDX-License-Identifier: AGPL-3.0-only
import AppKit
import SwiftUI
import Combine
import ServiceManagement

@MainActor final class AppDelegate: NSObject, NSApplicationDelegate {
    let model = AppModel()
    var item: NSStatusItem!
    let popover = NSPopover()
    private var observation: AnyCancellable?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.autosaveName = "MagicBayCellular"
        item.button?.target = self
        item.button?.action = #selector(togglePopover)
        item.button?.setAccessibilityLabel("Magic Bay LTE 蜂窝网络")
        popover.behavior = .transient
        popover.animates = true
        popover.contentViewController = NSHostingController(rootView: LTEPanel(model: model))
        popover.contentSize = NSSize(width: 376, height: 680)
        observation = model.$snapshot.sink { [weak self] value in self?.updateIcon(value) }
        model.begin()
        if CommandLine.arguments.contains("--show") {
            DispatchQueue.main.asyncAfter(deadline: .now()+0.8) { self.showPopover() }
        }
    }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showPopover()
        return true
    }
    @objc func togglePopover() {
        popover.isShown ? popover.performClose(nil) : showPopover()
    }
    func showPopover() {
        guard let button = item?.button else { return }
        model.refresh()
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        NSApp.activate(ignoringOtherApps: true)
        popover.contentViewController?.view.window?.makeKey()
    }
    func updateIcon(_ snapshot: Snapshot) {
        guard let button = item?.button else { return }
        let fill = snapshot.litBars
        let disconnected = !snapshot.connected
        let image = NSImage(size: NSSize(width: 22, height: 18), flipped: false) { rect in
            for index in 0..<4 {
                let height = CGFloat(4+index*3)
                let bar = NSBezierPath(roundedRect: NSRect(x: 1+CGFloat(index)*5, y: 2,
                    width: 3.4, height: height), xRadius: 1.05, yRadius: 1.05)
                if index < fill {
                    NSColor.black.setFill(); bar.fill()
                } else {
                    NSColor.black.withAlphaComponent(disconnected ? 0.16 : 0.22).setFill(); bar.fill()
                }
            }
            if disconnected {
                let line = NSBezierPath()
                line.move(to: NSPoint(x: 1,y: 1)); line.line(to: NSPoint(x: 20,y: 16))
                line.lineWidth=1.6; NSColor.black.withAlphaComponent(0.45).setStroke(); line.stroke()
            }
            return true
        }
        image.isTemplate = true
        button.image = image
        button.imagePosition = .imageLeading
        button.font = NSFont.systemFont(ofSize: 10, weight: .semibold)
        button.title = (snapshot.mode == .active || snapshot.mode == .returning) ? " LTE" : ""
        button.toolTip = "Magic Bay LTE · \(snapshot.heroTitle)\n\(snapshot.detail)" +
            (snapshot.dbm.map { "\n信号 \($0) dBm" } ?? "")
        button.setAccessibilityValue(snapshot.heroTitle)
    }
}

@MainActor func renderPreview(path: String, mode: String?) {
    let model = AppModel()
    model.snapshot = SnapshotReader.read()
    if let mode = mode, let value = ConnectionMode(rawValue: mode) {
        model.snapshot.mode = value
        model.snapshot.enabled = value != .disabled
        if value == .active { model.snapshot.detail = "蜂窝数据正在为这台 Mac 提供网络" }
        if value == .warning { model.snapshot.detail = "模块暂未就绪，后台正在间隔重试" }
        if value == .disabled { model.snapshot.dataConnected=false;model.snapshot.detail="模块已接入，LTE 未启用" }
    }
    let view = NSHostingView(rootView: LTEPanel(model: model))
    view.frame = NSRect(x: 0,y: 0,width: 376,height: 680)
    let window = NSWindow(contentRect: view.frame, styleMask: [.borderless], backing: .buffered, defer: false)
    window.contentView = view
    window.layoutIfNeeded()
    view.layoutSubtreeIfNeeded()
    RunLoop.current.run(until: Date().addingTimeInterval(0.3))
    guard let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { fatalError("No bitmap") }
    view.cacheDisplay(in: view.bounds,to: bitmap)
    guard let data = bitmap.representation(using: .png,properties: [:]) else { fatalError("No PNG") }
    try! data.write(to: URL(fileURLWithPath: path))
    print(path)
}

MainActor.assumeIsolated {
let arguments = CommandLine.arguments
if let index = arguments.firstIndex(of:"--render-about-preview"), arguments.count > index+1 {
    let app = NSApplication.shared
    app.setActivationPolicy(.prohibited)
    let view = NSHostingView(rootView:AboutView())
    let size = view.fittingSize
    view.frame = NSRect(origin:.zero,size:size)
    let window = NSWindow(contentRect:view.frame,styleMask:[.borderless],backing:.buffered,defer:false)
    window.contentView = view
    window.layoutIfNeeded()
    view.layoutSubtreeIfNeeded()
    guard let bitmap = view.bitmapImageRepForCachingDisplay(in:view.bounds) else { fatalError("No bitmap") }
    view.cacheDisplay(in:view.bounds,to:bitmap)
    try! bitmap.representation(using:.png,properties:[:])!.write(to:URL(fileURLWithPath:arguments[index+1]))
} else if arguments.contains("--register-login") {
    do {
        try LoginItem.setEnabled(true)
        print("LOGIN_STATUS \(SMAppService.mainApp.status.rawValue)")
    } catch { fputs("Login registration failed: \(error.localizedDescription)\n",stderr);exit(1) }
} else if arguments.contains("--unregister-login") {
    do {
        if SMAppService.mainApp.status != .notRegistered { try SMAppService.mainApp.unregister() }
    } catch { fputs("Login unregistration failed: \(error.localizedDescription)\n",stderr);exit(1) }
} else if arguments.contains("--login-status") {
    print("LOGIN_STATUS \(SMAppService.mainApp.status.rawValue)")
} else if arguments.contains("--self-test") {
    runModelChecks()
} else if let index = arguments.firstIndex(of: "--snapshot"), arguments.count>index+1 {
    let snapshot = SnapshotReader.read()
    let dictionary: [String: Any] = ["mode":snapshot.mode.rawValue,"title":snapshot.heroTitle,
        "enabled":snapshot.enabled,"metered":snapshot.metered as Any? ?? NSNull(),"signal_dbm":snapshot.dbm as Any? ?? NSNull(),
        "module_connected":snapshot.modulePresent as Any? ?? NSNull(),"data_connected":snapshot.dataConnected,
        "carrier":snapshot.carrierText,"sim":snapshot.simText,"network":snapshot.networkType,
        "signal_updated_utc":snapshot.signalUpdated.map { ISO8601DateFormatter().string(from:$0) } as Any? ?? NSNull(),
        "bars":snapshot.bars as Any? ?? NSNull(),"received":snapshot.received as Any? ?? NSNull(),
        "sent":snapshot.sent as Any? ?? NSNull(),"detail":snapshot.detail]
    let data = try! JSONSerialization.data(withJSONObject: dictionary,options: [.prettyPrinted,.sortedKeys])
    try! data.write(to: URL(fileURLWithPath: arguments[index+1]))
    print(String(decoding:data,as:UTF8.self))
} else if let index = arguments.firstIndex(of: "--render-preview"), arguments.count>index+1 {
    let app = NSApplication.shared
    app.setActivationPolicy(.prohibited)
    renderPreview(path: arguments[index+1],mode: arguments.count>index+2 ? arguments[index+2] : nil)
} else {
    let app = NSApplication.shared
    let identifier = Bundle.main.bundleIdentifier ?? "local.magicbay.lte.menu"
    let others = NSRunningApplication.runningApplications(withBundleIdentifier: identifier)
        .filter { $0.processIdentifier != ProcessInfo.processInfo.processIdentifier }
    if let other = others.first {
        other.activate(options: [])
    } else {
        let delegate = AppDelegate()
        app.delegate = delegate
        app.run()
    }
}
}
