// SPDX-License-Identifier: AGPL-3.0-only
import SwiftUI

let cellularGreen=Color(red:0.10,green:0.71,blue:0.40)
struct CellularBars: View {
    var filled: Int?
    var color: Color = .primary
    var disconnected=false
    var body: some View {
        HStack(alignment:.bottom,spacing:3) {
            ForEach(0..<4) { index in
                RoundedRectangle(cornerRadius:1.6,style:.continuous)
                    .fill(color.opacity(index<(filled ?? 0) ? 1 : 0.18))
                    .frame(width:5,height:CGFloat(7+index*5))
            }
        }.frame(width:29,height:22)
         .overlay {
             if disconnected {
                 Path { p in p.move(to:CGPoint(x:0,y:23));p.addLine(to:CGPoint(x:30,y:-1)) }
                     .stroke(color.opacity(0.55),style:StrokeStyle(lineWidth:1.7,lineCap:.round))
             }
         }
         .accessibilityLabel(filled.map { "蜂窝信号 \($0) 格，共 4 格" } ?? "蜂窝信号未知")
    }
}
struct SoftCard<Content: View>: View {
    @ViewBuilder var content: () -> Content
    var body: some View {
        content().padding(14)
            .background(Color.primary.opacity(0.045),in:RoundedRectangle(cornerRadius:20,style:.continuous))
            .overlay(RoundedRectangle(cornerRadius:20).strokeBorder(Color.primary.opacity(0.035)))
    }
}
struct LTEPanel: View {
    @ObservedObject var model: AppModel
    @State private var details=false
    private var s: Snapshot { model.snapshot }
    private var tint: Color { s.connected ? cellularGreen : .secondary }
    private func age(_ date: Date?) -> String {
        guard let date=date else { return "读取中" }
        let n=max(0,Int(Date().timeIntervalSince(date)))
        return n<5 ? "刚刚" : n<60 ? "\(n) 秒前" : "\(n/60) 分钟前"
    }
    private func row(_ symbol: String,_ name: String,_ value: String,good: Bool=false) -> some View {
        HStack(spacing:11) {
            Image(systemName:symbol).font(.system(size:14,weight:.medium))
                .foregroundStyle(.secondary).frame(width:20)
            Text(name).font(.system(size:12))
            Spacer()
            if good { Circle().fill(cellularGreen).frame(width:5,height:5) }
            Text(value).font(.system(size:12,weight:.medium)).foregroundStyle(good ? cellularGreen : .secondary)
        }
    }
    private func traffic(_ symbol: String,_ name: String,_ count: UInt64?,_ rate: Double) -> some View {
        VStack(alignment:.leading,spacing:7) {
            Label(name,systemImage:symbol).font(.system(size:11,weight:.medium)).foregroundStyle(.secondary)
            Text(readableBytes(count)).font(.system(size:23,weight:.semibold,design:.rounded)).monospacedDigit()
            Text(count==nil ? "—" : readableBytes(UInt64(max(0,rate)))+"/s")
                .font(.system(size:11)).monospacedDigit().foregroundStyle(.secondary)
        }.frame(maxWidth:.infinity,alignment:.leading)
    }
    var body: some View {
        VStack(spacing:0) {
            HStack {
                Text("Magic Bay LTE").font(.system(size:21,weight:.bold,design:.rounded))
                Spacer()
                Button { model.refresh() } label: { Image(systemName:"arrow.clockwise").frame(width:28,height:28) }
                    .buttonStyle(.plain).help("刷新 LTE 状态")
                Menu {
                    Button("重新连接 LTE") { model.reconnect() }
                        .disabled(model.busy || !model.snapshot.enabled)
                    Divider()
                    Link("运营商服务 · Lenovo Connect", destination: URL(string:"https://aoac.lenovoconnect.com/")!)
                    Divider()
                    Button("打开 LTE 日志") { model.openLogs() }
                    Toggle("登录时显示图标",isOn:Binding(get:{model.loginEnabled},set:{model.setLogin($0)}))
                    Divider()
                    Button("退出 Magic Bay LTE") { NSApplication.shared.terminate(nil) }
                } label: { Image(systemName:"ellipsis.circle").font(.system(size:18)).frame(width:28,height:28) }
                    .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize().help("更多选项")
            }.padding(.horizontal,22).padding(.top,20).padding(.bottom,17)
            ScrollView {
                VStack(spacing:11) {
                    SoftCard {
                        HStack(spacing:14) {
                            ZStack {
                                RoundedRectangle(cornerRadius:17,style:.continuous)
                                    .fill(LinearGradient(colors:[tint.opacity(0.85),tint],startPoint:.topLeading,endPoint:.bottomTrailing))
                                    .frame(width:62,height:62)
                                CellularBars(filled:s.litBars,color:.white,disconnected:!s.connected)
                                    .scaleEffect(1.2).accessibilityHidden(true)
                            }
                            VStack(alignment:.leading,spacing:7) {
                                Text(model.busy ? (model.desiredEnabled==true ? "正在连接 LTE" : "正在关闭 LTE") : s.heroTitle).font(.system(size:18,weight:.semibold))
                                Text(model.busy ? "正在更新连接设置" : s.detail).font(.system(size:12)).foregroundStyle(.secondary)
                                    .fixedSize(horizontal:false,vertical:true)
                            }
                            Spacer(minLength:0)
                        }
                    }
                    SoftCard {
                        HStack {
                            Text("启用 LTE").font(.system(size:13,weight:.semibold))
                            Spacer()
                            if model.busy { ProgressView().controlSize(.small) }
                            Toggle("启用 LTE",isOn:Binding(get:{model.desiredEnabled ?? s.enabled},set:{model.setEnabled($0)}))
                                .labelsHidden().toggleStyle(.switch).controlSize(.small).tint(cellularGreen)
                                .disabled(model.busy || !s.installed)
                        }
                    }
                    SoftCard {
                        VStack(spacing:13) {
                            row("cable.connector","模块",s.moduleText,good:s.modulePresent==true)
                            row("simcard","SIM 卡",s.simText,good:s.simState==1 && s.enabled)
                            Divider().opacity(0.6)
                            row("antenna.radiowaves.left.and.right","运营商",s.carrierText)
                            row("cellularbars","网络",s.enabled && s.modulePresent != false ? s.networkType+" · "+s.registrationText : "—")
                            row("link","数据连接",s.dataText,good:s.dataConnected)

                        }
                    }
                    SoftCard {
                        VStack(spacing:9) {
                            HStack {
                                Text("信号").font(.system(size:12,weight:.medium))
                                Spacer()
                                Text(s.dbm.map { "\($0) dBm" } ?? (s.enabled ? s.signalUpdated==nil ? "读取中" : "未知" : "—"))
                                    .font(.system(size:13,weight:.medium)).monospacedDigit().foregroundStyle(.secondary)
                                CellularBars(filled:s.litBars,color:s.connected ? cellularGreen : .secondary,disconnected:!s.connected)
                                    .scaleEffect(0.8).frame(width:27,height:21)
                                Button { model.detectSignal() } label: {
                                    HStack(spacing:4) {
                                        if model.signalBusy { ProgressView().controlSize(.mini) }
                                        Text(model.signalBusy ? "检测中" : "检测")
                                    }
                                }.font(.system(size:11,weight:.medium)).buttonStyle(.bordered).controlSize(.small)
                                    .disabled(model.signalBusy || !s.enabled || !s.modemAvailable || s.modulePresent != true).help("立即检测 LTE 信号")
                            }
                            HStack {
                                Text("RSSI")
                                Spacer()
                                Text(s.signalUpdated==nil ? "等待模块响应" : "每 30 秒检测 · "+age(s.signalUpdated))
                            }.font(.system(size:10)).foregroundStyle(.tertiary)
                        }
                    }
                    VStack(alignment:.leading,spacing:8) {
                        Text("本次 LTE 流量").font(.system(size:11,weight:.medium)).foregroundStyle(.secondary).padding(.horizontal,4)
                        SoftCard {
                            HStack(spacing:20) {
                                traffic("arrow.down","下载",s.received,s.downloadRate)
                                Rectangle().fill(Color.primary.opacity(0.08)).frame(width:1,height:52)
                                traffic("arrow.up","上传",s.sent,s.uploadRate)
                            }
                        }
                    }
                    if let notice=model.notice {
                        Text(notice).font(.system(size:11)).foregroundStyle(.secondary)
                            .padding(.horizontal,4).frame(maxWidth:.infinity,alignment:.leading)
                    }
                    DisclosureGroup(isExpanded:$details) {
                        VStack(spacing:8) {
                            detailRow("IPv4",s.ipv4 ?? "—")
                            detailRow("运营商代码",s.providerId ?? "—")
                            detailRow("网络计费",s.mode == .ready ? "数据未启用" : s.enabled ? s.metered.map { $0 ? "按流量计费" : "未标记" } ?? "读取中" : "—")
                            detailRow("连接时间",s.connectedAt.map {$0.formatted(date:.omitted,time:.shortened)} ?? "—")
                            detailRow("联网检查",s.lteHealthy.map {$0 ? "最近一次通过" : "未通过"} ?? "尚未检查")
                            Text("流量来自 LTE 接口统计，包含后台检测，不是运营商账单。")
                                .font(.system(size:10)).foregroundStyle(.tertiary).fixedSize(horizontal:false,vertical:true)
                        }.padding(.top,12)
                    } label: { Text("更多信息").font(.system(size:11)) }
                        .foregroundStyle(.secondary).padding(.horizontal,4)
                }.padding(.horizontal,18).padding(.bottom,14)
            }.scrollIndicators(.hidden)
            HStack(spacing:6) {
                Circle().fill(s.mode == .warning ? .orange : Color.secondary.opacity(0.5)).frame(width:4,height:4)
                Text("状态更新于 "+age(s.updated)).font(.system(size:10))
                Spacer()
                Link(destination: URL(string:"https://github.com/Zachery-Liu/MagicBayLTE")!) {
                    HStack(spacing:4) {
                        GitHubMark().frame(width:12,height:12).accessibilityHidden(true)
                        Text("ZacheryLiu").font(.system(size:10,weight:.medium))
                        Image(systemName:"arrow.up.right").font(.system(size:8,weight:.semibold))
                    }.contentShape(Rectangle())
                }.buttonStyle(.plain).foregroundStyle(.secondary)
                    .help("在 GitHub 查看 MagicBayLTE 项目")
                    .accessibilityLabel("GitHub · ZacheryLiu，打开 MagicBayLTE 仓库")
            }.foregroundStyle(.tertiary).padding(.horizontal,23).padding(.vertical,13)
        }.frame(width:376,height:680).background(.ultraThinMaterial).accentColor(cellularGreen)
    }
    private func detailRow(_ name: String,_ value: String) -> some View {
        HStack { Text(name);Spacer();Text(value).textSelection(.enabled) }.font(.system(size:11))
    }
}
