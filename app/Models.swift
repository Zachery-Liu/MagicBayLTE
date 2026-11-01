// SPDX-License-Identifier: AGPL-3.0-only
import Foundation
import Darwin

struct ProxyState: Decodable {
    var compatible: Bool?
    var reason: String?
}
struct ServiceState: Decodable {
    var pid: Int32?
    var phase: String
    var active: Bool?
    var updatedUtc: String?
    var interface: String?
    var enginePid: Int32?
    var engineLog: String?
    var lteHealth: Bool?
    var lteExpensive: Bool?
    var proxy: ProxyState?
    var observeOnly: Bool?
    var error: String?
    var connectionStartedUtc: String?
    var retryCount: Int?
    var transferReceivedTotal: UInt64?
    var transferSentTotal: UInt64?
    var reconnectCount: Int?
}
struct HelperState: Decodable {
    var pid: Int32
    var enabled: Bool
    var phase: String
    var enabledUtc: String?
    var updatedUtc: String
    var protocolVersion: Int
}
struct ModemState: Decodable {
    var enginePid: Int32
    var updatedUtc: String
    var simState: Int
    var registrationState: Int
    var packetState: Int
    var activationState: Int
    var dataClass: UInt32
    var providerName: String
    var providerId: String
    var rssi: Int
    var signalUpdatedUtc: String
    var registrationUpdatedUtc: String
    var simUpdatedUtc: String
    var packetUpdatedUtc: String
    var activationUpdatedUtc: String
}
enum ConnectionMode: String {
    case ready, returning, standby, active, preparing, reconnecting, waiting, closing, disabled, warning
    var title: String {
        switch self {
        case .ready: return "LTE 已就绪"
        case .returning: return "正在切回原网络"
        case .standby: return "LTE 数据连接待确认"
        case .active: return "正在使用 LTE"
        case .preparing: return "正在连接 LTE"
        case .reconnecting: return "正在重新连接 LTE"
        case .waiting: return "等待接入模块"
        case .closing: return "正在关闭 LTE"
        case .disabled: return "LTE 未启用"
        case .warning: return "连接需要检查"
        }
    }
}
struct Snapshot {
    var mode: ConnectionMode = .preparing
    var detail = "正在读取 LTE 状态…"
    var enabled = false
    var reconnectCount = 0
    var modulePresent: Bool?
    var dataConnected = false
    var simState: Int?
    var registrationState: Int?
    var providerName: String?
    var providerId: String?
    var networkType = "读取中"
    var bars: Int?
    var dbm: Int?
    var signalUpdated: Date?
    var lteHealthy: Bool?
    var metered: Bool?
    var interface: String?
    var ipv4: String?
    var updated: Date?
    var connectedAt: Date?
    var logURL: URL?
    var received: UInt64?
    var sent: UInt64?
    var downloadRate: Double = 0
    var uploadRate: Double = 0
    var compatible = true
    var installed = false
    var modemAvailable = false
    var connected: Bool {
        enabled && modulePresent == true && ((dataConnected && (mode == .standby || mode == .active || mode == .returning)) ||
            (mode == .ready && simState==1 && [3,4,5].contains(registrationState ?? -1)))
    }
    var dataText: String {
        if mode == .returning { return "正在结束" }
        if mode == .ready { return "未建立 · 待命" }
        return dataConnected ? "已连接" : enabled && modulePresent==true ? "连接中" : "未连接"
    }
    var litBars: Int { connected ? min(4,max(0,bars ?? 0)) : 0 }
    var moduleText: String { modulePresent.map { $0 ? "已接入" : "未接入" } ?? "未知" }
    var simText: String {
        guard enabled && modulePresent != false else { return "—" }
        switch simState {
        case 1: return "已就绪"
        case 2: return "未插卡"
        case 3: return "SIM 卡异常"
        case 6: return "SIM 已锁定"
        case 0, 4, 5: return "尚未就绪"
        default: return "读取中"
        }
    }
    var carrierText: String {
        guard enabled && modulePresent != false else { return "—" }
        if let name=providerName, !name.isEmpty {
            if name.uppercased()=="CHN-UNICOM" { return "中国联通" }
            return name
        }
        if let id=providerId, !id.isEmpty { return id }
        return "读取中"
    }
    var registrationText: String {
        guard enabled && modulePresent != false else { return "—" }
        switch registrationState {
        case 3, 5: return "已注册"
        case 4: return "漫游"
        case 2: return "搜索中"
        case 1: return "未注册"
        case 6: return "注册被拒绝"
        default: return "读取中"
        }
    }
    var heroTitle: String {
        if modulePresent == false { return "模块未连接" }
        return mode.title
    }
}

enum SnapshotReader {
    static let root = URL(fileURLWithPath: "/Library/Application Support/MagicBayLTE", isDirectory: true)
    static func processAlive(_ pid: Int32?) -> Bool {
        guard let pid=pid,pid>1 else { return false }
        return kill(pid,0)==0 || errno==EPERM
    }
    static func date(_ text: String?) -> Date? {
        guard let text=text, !text.isEmpty else { return nil }
        let format=ISO8601DateFormatter();format.formatOptions=[.withInternetDateTime,.withFractionalSeconds]
        return format.date(from:text)
    }
    static func capture(_ pattern: String, _ text: String) -> String? {
        guard let regex=try? NSRegularExpression(pattern:pattern),
              let match=regex.firstMatch(in:text,range:NSRange(text.startIndex...,in:text)),
              let range=Range(match.range(at:1),in:text) else { return nil }
        return String(text[range])
    }
    static func interpret(_ state: ServiceState, now: Date, processAlive: Bool) -> Snapshot {
        var result=Snapshot()
        result.installed=true
        result.reconnectCount=state.reconnectCount ?? 0
        result.updated=date(state.updatedUtc)
        result.enabled=processAlive && state.phase != "stopped" && state.phase != "cleanup_pending"
        result.received=state.transferReceivedTotal
        result.sent=state.transferSentTotal
        result.interface=state.interface
        result.lteHealthy=state.lteHealth
        result.metered=state.lteExpensive
        result.compatible=state.proxy?.compatible ?? true
        if !result.enabled {
            result.mode=state.phase=="cleanup_pending" ? .warning : .disabled
            result.detail=state.phase=="cleanup_pending" ? "上次连接仍在清理" : "LTE 未启用"
        } else if result.updated == nil || now.timeIntervalSince(result.updated!)>60 {
            result.mode = .warning;result.detail="后台状态更新超时"
            result.lteHealthy=nil
        } else if state.phase=="reconnecting" {
            result.mode = .reconnecting;result.detail="正在结束旧 LTE 会话，随后重新初始化"
        } else if state.phase=="waiting_module" {
            result.mode = .waiting;result.detail="接入 Magic Bay LTE 后将自动初始化"
        } else if state.phase=="return_check" {
            result.mode = .warning;result.detail="蜂窝数据已关闭，当前联网检查未通过"
        } else if state.phase=="returning" {
            result.mode = .returning;result.detail="正在确认 LTE 数据会话已关闭及原网络可用"
        } else if state.phase=="ready" {
            result.mode = .ready;result.detail="数据会话未建立，按需接管"
        } else if state.phase=="LTE" && state.active==true {
            result.mode = .active;result.detail="蜂窝数据传输中"
        } else if state.phase=="standby" {
            result.mode=state.lteHealth==false ? .warning : .standby
            result.detail=state.lteHealth==false ? "联网检查未通过" : "数据链路已建立"
        } else if state.phase=="retrying" {
            let elapsed=date(state.connectionStartedUtc).map { now.timeIntervalSince($0) } ?? 0
            let prolonged=elapsed>=180 && (state.retryCount ?? 0)>=3
            result.mode = prolonged ? .warning : .preparing
            result.detail=prolonged ? "多次连接未成功，后台仍在重试，请查看日志" : "模块正在准备，稍后自动重试"
        } else { result.mode = .preparing;result.detail="正在建立蜂窝连接" }
        return result
    }
    static func applyModem(_ modem: ModemState, to snapshot: inout Snapshot, now: Date, enginePid: Int32?) {
        guard snapshot.enabled, snapshot.modulePresent != false,
              modem.enginePid==enginePid, let updated=date(modem.updatedUtc),
              now.timeIntervalSince(updated)<90 else { return }
        if let at=date(modem.simUpdatedUtc), now.timeIntervalSince(at)<90 {
            snapshot.simState=modem.simState>=0 ? modem.simState : nil
        }
        if let at=date(modem.registrationUpdatedUtc), now.timeIntervalSince(at)<90 {
            snapshot.registrationState=modem.registrationState>=0 ? modem.registrationState : nil
            snapshot.providerName=modem.providerName
            snapshot.providerId=modem.providerId
        }
        if let at=date(modem.packetUpdatedUtc), now.timeIntervalSince(at)<90 {
            snapshot.networkType=modem.dataClass & 0x20 != 0 ? "4G LTE" : modem.dataClass>0 ? "移动网络" : "未注册"
        }
        if let at=date(modem.activationUpdatedUtc), now.timeIntervalSince(at)<90 {
            snapshot.dataConnected=modem.activationState==1
            if snapshot.mode == .ready && modem.activationState != 3 {
                snapshot.mode = .warning;snapshot.detail="数据会话状态尚未确认，正在检查"
            }
        }
        if let at=date(modem.signalUpdatedUtc), now.timeIntervalSince(at)<75 {
            snapshot.signalUpdated=at
            if (0...31).contains(modem.rssi) {
                snapshot.dbm = -113+2*modem.rssi
                snapshot.bars=modem.rssi>=17 ? 4 : modem.rssi>=12 ? 3 : modem.rssi>=7 ? 2 : modem.rssi>=2 ? 1 : 0
            } else { snapshot.dbm=nil;snapshot.bars=nil }
        } else { snapshot.dbm=nil;snapshot.bars=nil }
    }
    static func applyHelper(_ helper: HelperState, to result: inout Snapshot, supervisorAlive: Bool) {
        result.enabled=helper.enabled
        result.updated=date(helper.updatedUtc)
        if helper.phase=="stopping" {
            result.mode = .closing;result.detail="正在释放蜂窝连接"
        } else if !helper.enabled {
            result.mode = .disabled;result.detail="LTE 未启用"
        } else if !supervisorAlive || result.mode == .disabled {
            result.mode = .preparing;result.detail="正在准备蜂窝连接"
        }
        if !helper.enabled || !supervisorAlive || helper.phase=="starting" || helper.phase=="stopping" {
            result.dataConnected=false;result.interface=nil;result.lteHealthy=nil;result.metered=nil
        }
    }
    static func read() -> Snapshot {
        var result=Snapshot()
        let detected=mb_module_present()
        let presence: Bool?=detected<0 ? nil : detected==1
        result.modulePresent=presence
        result.installed=FileManager.default.fileExists(atPath:root.appendingPathComponent("lte_auto.py").path)
        let decoder=JSONDecoder();decoder.keyDecodingStrategy = .convertFromSnakeCase
        let helper=(try? Data(contentsOf:root.appendingPathComponent("helper-state.json")))
            .flatMap { try? decoder.decode(HelperState.self,from:$0) }
        let liveHelper=helper.flatMap { h -> HelperState? in
            guard h.protocolVersion==1, processAlive(h.pid), h.phase != "offline",
                  let stamp=date(h.updatedUtc), Date().timeIntervalSince(stamp)<15 else { return nil }
            return h
        }
        guard let data=try? Data(contentsOf:root.appendingPathComponent("auto-state.json")) else {
            result.mode = .disabled;result.detail=presence==true ? "模块已接入" : "等待模块接入"
            if let h=liveHelper { applyHelper(h,to:&result,supervisorAlive:false) }
            return result
        }
        guard let state=try? decoder.decode(ServiceState.self,from:data) else {
            result.mode = .warning;result.detail="暂时无法读取 LTE 状态";return result
        }
        let alive=processAlive(state.pid)
        result=interpret(state,now:Date(),processAlive:alive)
        result.modulePresent=presence
        if let h=liveHelper { applyHelper(h,to:&result,supervisorAlive:alive) }
        result.modemAvailable=result.enabled && alive && liveHelper?.phase != "stopping" && processAlive(state.enginePid) && state.phase != "retrying"
        if let path=state.engineLog {
            let candidate=URL(fileURLWithPath:path).standardizedFileURL
            let directory=root.appendingPathComponent("logs").standardizedFileURL.path+"/"
            if candidate.path.hasPrefix(directory) {
                result.logURL=candidate
                if let handle=try? FileHandle(forReadingFrom:candidate) {
                    let data=try? handle.read(upToCount:131072);try? handle.close()
                    let text=String(decoding:data ?? Data(),as:UTF8.self)
                    result.ipv4=capture(#"IPv4\s*:\s*([0-9.]+)"#,text)
                    result.connectedAt=date(capture(#"\[(\d{4}-\d\d-\d\dT[^\]]+Z)\] engine start"#,text))
                }
            }
        }
        if result.enabled,result.modemAvailable,presence != false,let name=state.interface,
           name.range(of:#"^utun\d+$"#,options:.regularExpression) != nil {
            var rx: UInt64=0,tx: UInt64=0
            if mb_interface_counters(name,&rx,&tx)==0 {
                if result.received==nil { result.received=rx }
                if result.sent==nil { result.sent=tx }
                result.dataConnected=result.lteHealthy==true
            }
        }
        if result.modemAvailable,let bytes=try? Data(contentsOf:root.appendingPathComponent("modem-state.json")),
           let modem=try? decoder.decode(ModemState.self,from:bytes) {
            applyModem(modem,to:&result,now:Date(),enginePid:state.enginePid)
        }
        if presence==false {
            result.mode=result.enabled ? .waiting : .disabled
            result.detail="等待接入 Magic Bay LTE 模块"
            result.dataConnected=false;result.simState=nil;result.providerName=nil;result.providerId=nil
            result.bars=nil;result.dbm=nil;result.signalUpdated=nil
        } else if result.dataConnected && (result.mode == .standby || result.mode == .active) {
            let carrier=result.carrierText
            result.detail=carrier=="读取中" ? "运营商信息读取中" : carrier+" · "+result.networkType
        } else if !result.enabled && result.mode != .closing { result.detail=presence==true ? "模块已接入，LTE 未启用" : "LTE 未启用" }
        return result
    }
}

func readableBytes(_ value: UInt64?) -> String {
    guard let value=value else { return "—" }
    if value<1000 { return "\(value) B" }
    let units=["KB","MB","GB","TB","PB","EB"]
    var amount=Double(value)/1000,index=0
    while amount>=1000 && index<units.count-1 { amount/=1000;index+=1 }
    return String(format:amount<10 ? "%.1f %@" : "%.0f %@",amount,units[index])
}
func runModelChecks() {
    let now=Date();let format=ISO8601DateFormatter();format.formatOptions=[.withInternetDateTime,.withFractionalSeconds]
    let stamp=format.string(from:now)
    var state=ServiceState(pid:42,phase:"standby",active:false,updatedUtc:stamp,enginePid:51,lteHealth:true)
    precondition(SnapshotReader.interpret(state,now:now,processAlive:true).mode == .standby)
    state.lteExpensive=true
    precondition(SnapshotReader.interpret(state,now:now,processAlive:true).metered == true)
    var readyState=state;readyState.phase="ready";readyState.interface=nil
    var ready=SnapshotReader.interpret(readyState,now:now,processAlive:true)
    ready.modulePresent=true;ready.simState=1;ready.registrationState=3;ready.bars=4
    precondition(ready.mode == .ready && ready.connected && !ready.dataConnected && ready.dataText=="未建立 · 待命")
    var absent=readyState;absent.phase="waiting_module"
    precondition(SnapshotReader.interpret(absent,now:now,processAlive:true).mode == .waiting)
    readyState.phase="returning"
    precondition(SnapshotReader.interpret(readyState,now:now,processAlive:true).mode == .returning)
    precondition(SnapshotReader.interpret(state,now:now,processAlive:false).mode == .disabled)
    precondition(SnapshotReader.interpret(state,now:now.addingTimeInterval(61),processAlive:true).mode == .warning)
    state.phase="LTE";state.active=true
    precondition(SnapshotReader.interpret(state,now:now,processAlive:true).mode == .active)
    var retry=state;retry.phase="retrying";retry.active=false;retry.connectionStartedUtc=stamp;retry.retryCount=2
    precondition(SnapshotReader.interpret(retry,now:now,processAlive:true).mode == .preparing)
    retry.retryCount=3;retry.connectionStartedUtc=format.string(from:now.addingTimeInterval(-181))
    precondition(SnapshotReader.interpret(retry,now:now,processAlive:true).mode == .warning)
    var idle=Snapshot()
    let helper=HelperState(pid:42,enabled:false,phase:"disabled",enabledUtc:stamp,updatedUtc:stamp,protocolVersion:1)
    SnapshotReader.applyHelper(helper,to:&idle,supervisorAlive:false)
    precondition(!idle.enabled && idle.mode == .disabled)
    var stopping=helper;stopping.phase="stopping"
    SnapshotReader.applyHelper(stopping,to:&idle,supervisorAlive:true)
    precondition(idle.mode == .closing && !idle.dataConnected)
    var snapshot=SnapshotReader.interpret(state,now:now,processAlive:true)
    snapshot.modulePresent=true
    var modem=ModemState(enginePid:51,updatedUtc:stamp,simState:1,registrationState:3,packetState:2,
        activationState:1,dataClass:32,providerName:"CHN-UNICOM",providerId:"46001",rssi:27,
        signalUpdatedUtc:stamp,registrationUpdatedUtc:stamp,simUpdatedUtc:stamp,packetUpdatedUtc:stamp,activationUpdatedUtc:stamp)
    SnapshotReader.applyModem(modem,to:&snapshot,now:now,enginePid:51)
    precondition(snapshot.carrierText=="中国联通" && snapshot.simText=="已就绪" && snapshot.dbm == -59 && snapshot.dataConnected)
    precondition(snapshot.networkType=="4G LTE" && snapshot.bars==4 && snapshot.moduleText=="已接入")
    precondition(snapshot.connected && snapshot.litBars==4)
    var disconnected=snapshot;disconnected.modulePresent=false
    precondition(!disconnected.connected && disconnected.litBars==0)
    var stale=Snapshot();stale.enabled=true;stale.modulePresent=true
    SnapshotReader.applyModem(modem,to:&stale,now:now,enginePid:52)
    precondition(stale.dbm==nil && stale.providerName==nil)
    modem.rssi=99
    SnapshotReader.applyModem(modem,to:&snapshot,now:now,enginePid:51)
    precondition(snapshot.dbm==nil && snapshot.bars==nil)
    precondition(readableBytes(0)=="0 B")
    precondition(!SnapshotReader.processAlive(nil) && !SnapshotReader.processAlive(1))
    precondition(SnapshotReader.processAlive(ProcessInfo.processInfo.processIdentifier))
    print("PASS: LTE-only states, module presence, carrier, SIM, session, live/unknown signal and old-engine rejection")
}
