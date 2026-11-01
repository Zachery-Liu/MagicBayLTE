// SPDX-License-Identifier: AGPL-3.0-only
import AppKit
import Combine
import SwiftUI
import ServiceManagement

@MainActor final class AppModel: ObservableObject {
    @Published var snapshot = Snapshot()
    @Published var busy = false
    @Published var desiredEnabled: Bool?
    @Published var notice: String?
    @Published var signalBusy = false
    @Published var loginEnabled = LoginItem.isEnabled
    private var pendingSince: Date?
    private var reading = false
    private var previous: (key: String, rx: UInt64, tx: UInt64, time: Double)?
    private var timer: Timer?
    private var signalRequestedAt: Date?
    private var pendingReconnect: (count: Int, started: Date)?

    func begin() {
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
        RunLoop.main.add(timer!, forMode: .common)
    }
    func refresh() {
        guard !reading else { return }
        reading = true
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let result = SnapshotReader.read()
            DispatchQueue.main.async {
                guard let self = self else { return }
                var result = result
                let now = ProcessInfo.processInfo.systemUptime
                let key = (result.interface ?? "") + (result.logURL?.path ?? "")
                if let rx = result.received, let tx = result.sent {
                    if let old = self.previous, old.key == key, now > old.time,
                       rx >= old.rx, tx >= old.tx {
                        result.downloadRate = Double(rx-old.rx)/(now-old.time)
                        result.uploadRate = Double(tx-old.tx)/(now-old.time)
                    }
                    self.previous = (key, rx, tx, now)
                } else { self.previous = nil }
                if let pending=self.pendingReconnect {
                    if result.reconnectCount>pending.count && result.mode != .reconnecting {
                        self.pendingReconnect=nil;self.busy=false
                    } else if Date().timeIntervalSince(pending.started)>60 {
                        self.pendingReconnect=nil;self.busy=false
                        self.notice="重新连接尚未完成，请查看 LTE 状态或日志。"
                    } else {
                        result.mode = .reconnecting;result.detail="正在结束旧 LTE 会话并重新初始化"
                        result.dataConnected=false
                    }
                }
                self.snapshot = result
                if let pending=self.pendingSince {
                    if result.enabled==self.desiredEnabled {
                        self.busy=false;self.desiredEnabled=nil;self.pendingSince=nil
                    } else if Date().timeIntervalSince(pending)>6 {
                        self.busy=false;self.desiredEnabled=nil;self.pendingSince=nil
                        self.notice="后台尚未确认设置，请稍后刷新。"
                    }
                }
                if let requested=self.signalRequestedAt {
                    if let measured=result.signalUpdated, measured>requested {
                        self.signalBusy=false;self.signalRequestedAt=nil
                    } else if Date().timeIntervalSince(requested)>12 {
                        self.signalBusy=false;self.signalRequestedAt=nil
                        self.notice="暂未收到新的信号结果，请稍后再试。"
                    }
                }
                self.reading = false
            }
        }
    }
    func detectSignal() {
        guard !signalBusy, snapshot.enabled, snapshot.modemAvailable, snapshot.modulePresent==true else { refresh();return }
        do {
            let requested=Date()
            let handle=try FileHandle(forWritingTo:SnapshotReader.root.appendingPathComponent("signal-request"))
            defer { try? handle.close() }
            try handle.seek(toOffset:0)
            try handle.write(contentsOf:Data([1]))
            signalRequestedAt=requested;signalBusy=true;notice=nil
            refresh()
        } catch { notice="无法发起信号检测，请确认 LTE 服务已更新。" }
    }
    func setEnabled(_ enabled: Bool) {
        guard !busy else { return }
        guard snapshot.installed else {
            notice = "LTE 服务尚未安装。"
            return
        }
        busy = true
        desiredEnabled = enabled
        notice = nil
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let accepted = mb_set_enabled(enabled ? 1 : 0) == 0
            DispatchQueue.main.async {
                guard let self = self else { return }
                if !accepted {
                    self.busy = false
                    self.desiredEnabled = nil
                    self.notice = "无法联系后台助手，请检查后台服务是否已更新。"
                } else {
                    self.pendingSince = Date()
                }
                self.refresh()
            }
        }
    }
    func setLogin(_ enabled: Bool) {
        do { try LoginItem.setEnabled(enabled); loginEnabled = enabled }
        catch { notice = "登录启动设置未保存：\(error.localizedDescription)" }
    }
    func reconnect() {
        guard !busy, snapshot.installed, snapshot.enabled else { return }
        let count=snapshot.reconnectCount
        busy=true;notice=nil
        DispatchQueue.global(qos:.userInitiated).async { [weak self] in
            let accepted=mb_reconnect()==0
            DispatchQueue.main.async {
                guard let self=self else { return }
                if accepted { self.pendingReconnect=(count,Date()) }
                else { self.busy=false;self.notice="后台尚未接受重新连接，请稍后再试。" }
                self.refresh()
            }
        }
    }
    func openLogs() {
        NSWorkspace.shared.open(SnapshotReader.root.appendingPathComponent("logs", isDirectory: true))
    }
}

@MainActor enum LoginItem {
    static let label = "local.magicbay.lte.menu"
    static var url: URL { FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/LaunchAgents/\(label).plist") }
    static var isEnabled: Bool {
        SMAppService.mainApp.status == .enabled || FileManager.default.fileExists(atPath:url.path)
    }
    static func setEnabled(_ enabled: Bool) throws {
        if enabled {
            if SMAppService.mainApp.status != .enabled { try SMAppService.mainApp.register() }
            guard SMAppService.mainApp.status == .enabled else {
                throw NSError(domain:"MagicBayLTE",code:1,userInfo:[NSLocalizedDescriptionKey:"请在系统设置中允许登录启动。"])
            }
        } else {
            if SMAppService.mainApp.status != .notRegistered { try SMAppService.mainApp.unregister() }
            if FileManager.default.fileExists(atPath:url.path) { try FileManager.default.removeItem(at:url) }
        }
    }
}
