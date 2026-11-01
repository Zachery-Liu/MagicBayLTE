// SPDX-License-Identifier: AGPL-3.0-only
import AppKit
import SwiftUI

struct AboutView: View {
    private var version: String {
        Bundle.main.object(forInfoDictionaryKey:"CFBundleShortVersionString") as? String ?? ""
    }
    private func license(_ title: String, _ file: String) -> some View {
        Button {
            if let url = Bundle.main.url(forResource:file, withExtension:nil, subdirectory:"Licenses") {
                NSWorkspace.shared.open(url)
            }
        } label: {
            HStack { Text(title); Spacer(); Image(systemName:"doc.text") }
                .frame(maxWidth:.infinity)
        }.buttonStyle(.plain).padding(.vertical,5)
    }
    var body: some View {
        VStack(alignment:.leading,spacing:18) {
            HStack(spacing:14) {
                Image(nsImage:NSImage(named:NSImage.applicationIconName) ?? NSImage())
                    .resizable().frame(width:60,height:60)
                VStack(alignment:.leading,spacing:5) {
                    Text("Magic Bay LTE").font(.system(size:24,weight:.bold,design:.rounded))
                    Text("版本 \(version)").font(.subheadline).foregroundStyle(.secondary)
                }
            }
            Text("Copyright © 2026 Zachery Liu and contributors")
                .font(.system(size:11)).foregroundStyle(.secondary)
            VStack(alignment:.leading,spacing:8) {
                Text("自由软件 · AGPL-3.0-only").font(.headline)
                Text("你可以按照 GNU Affero General Public License 第 3 版的条款使用、修改和再分发本软件。软件按现状提供，不附带任何担保，包括适销性或特定用途适用性的担保。")
                    .font(.system(size:12)).fixedSize(horizontal:false,vertical:true)
                Text("独立社区项目，非 Lenovo 或 Apple 官方产品。")
                    .font(.system(size:11)).foregroundStyle(.secondary)
            }
            VStack(spacing:0) {
                license("GNU AGPL v3 · 许可证全文", "AGPL-3.0.txt")
                Divider()
                license("版权与第三方组件声明", "NOTICE.txt")
                license("MBIM 引擎 · MIT", "MIT-cellular.txt")
                license("libusb · LGPL 2.1 或更新版本", "LGPL-2.1.txt")
                license("GitHub Octicons · MIT", "MIT-Octicons.txt")
            }.font(.system(size:12)).padding(14)
                .background(Color.primary.opacity(0.045),in:RoundedRectangle(cornerRadius:14))
            HStack {
                Link(destination:URL(string:"https://github.com/Zachery-Liu/MagicBayLTE")!) {
                    Label("项目源码 ↗",systemImage:"chevron.left.forwardslash.chevron.right")
                }
                Spacer()
                Button("本机对应源码") {
                    NSWorkspace.shared.open(URL(fileURLWithPath:"/Library/Application Support/MagicBayLTE/Source",isDirectory:true))
                }.buttonStyle(.link)
            }.font(.system(size:12))
        }.padding(26).frame(width:470).background(.regularMaterial)
    }
}

@MainActor enum AboutWindow {
    private static var window: NSWindow?
    static func show() {
        if window == nil {
            let controller = NSHostingController(rootView:AboutView())
            let created = NSWindow(contentViewController:controller)
            created.title = "关于与开源许可证"
            created.styleMask = [.titled,.closable]
            created.isReleasedWhenClosed = false
            created.center()
            window = created
        }
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps:true)
    }
}
