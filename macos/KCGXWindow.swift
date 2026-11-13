// KCGX.app: the cockpit in a window of its own.
//
// One window holding one WKWebView on the local kcgx server. The server
// plays the audio; this only shows its page. Built by macos/build.sh.
//
//   kcgx://show?port=8473&fragment=airport%3Dseattle
//       how the launcher opens it: show the cockpit on that port, and hand
//       the page that fragment (`kcgx go`'s airport search)
//   opened with no link (the Dock, Spotlight)
//       start the cockpit with <KCGXRepo>/bin/kcgx --no-open, then show it
//   the red close button hides it, as Hide does, and the audio plays on
//   Quit, or the page's power icon, stops the cockpit
//
// Any web page can open a kcgx:// link, so a link can ask for very little:
// a port and a fragment. The host is always 127.0.0.1, and whatever answers
// on the port must say it is kcgx before anything is loaded from it. See
// Target.
//
// Two arguments, for checking a build from a terminal:
//   KCGX --port N        show the cockpit on port N, as a link would
//   KCGX --check LINK    print the page LINK would show, or "refused"; no window

import Cocoa
import WebKit

let host = "127.0.0.1"

/// A cockpit this window may show: a port on this machine, and a fragment
/// for its page.
struct Target {
    let port: Int
    let fragment: String

    /// The port must be written as a plain whole number from 1024 to 65535.
    init?(port text: String, fragment: String = "") {
        let digits = text.utf8
        guard (1...5).contains(digits.count), digits.allSatisfy({ (0x30...0x39).contains($0) }),
              let port = Int(text), (1024...65535).contains(port),
              fragment.utf8.count <= 512 else { return nil }
        self.port = port
        self.fragment = Target.legal(fragment)
    }

    /// A kcgx://show link. It may name `port` and `fragment`, once each,
    /// and nothing else: no path, no user, no other parameter.
    init?(link: URL) {
        guard let parts = URLComponents(url: link, resolvingAgainstBaseURL: false),
              parts.scheme?.lowercased() == "kcgx", parts.host?.lowercased() == "show",
              parts.user == nil, parts.password == nil, parts.port == nil,
              parts.path.isEmpty, parts.fragment == nil else { return nil }
        var asked: [String: String] = [:]
        for item in parts.queryItems ?? [] {
            guard item.name == "port" || item.name == "fragment", asked[item.name] == nil,
                  let value = item.value else { return nil }
            asked[item.name] = value
        }
        guard let port = asked["port"] else { return nil }
        self.init(port: port, fragment: asked["fragment"] ?? "")
    }

    /// The cockpit's page, and the same with the fragment for it.
    var home: URL { URL(string: "http://\(host):\(port)/")! }
    var page: URL { fragment.isEmpty ? home : URL(string: "\(home.absoluteString)#\(fragment)")! }

    func api(_ name: String) -> URL { URL(string: "http://\(host):\(port)/api/\(name)")! }

    /// `text` as a URL's fragment and nothing more. What a fragment may
    /// hold is kept, with any %XX escape; every other byte is escaped. The
    /// result cannot end the fragment, and has no quote or backslash in it.
    static func legal(_ text: String) -> String {
        let plain = Set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~!$&'()*+,;=:@/?".utf8)
        let hex = Set("0123456789ABCDEFabcdef".utf8)
        let bytes = Array(text.utf8)
        var out = ""
        var at = 0
        while at < bytes.count {
            let byte = bytes[at]
            if byte == 0x25, at + 2 < bytes.count, hex.contains(bytes[at + 1]), hex.contains(bytes[at + 2]) {
                out += String(decoding: bytes[at...at + 2], as: UTF8.self)
                at += 3
                continue
            }
            out += plain.contains(byte) ? String(UnicodeScalar(byte)) : String(format: "%%%02X", byte)
            at += 1
        }
        return out
    }
}

final class Cockpit: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKScriptMessageHandler {
    private var window: NSWindow!
    private var web: WKWebView!
    private var titleWatch: NSKeyValueObservation?
    private let session: URLSession = {
        let plain = URLSessionConfiguration.ephemeral
        plain.connectionProxyDictionary = [:]  // this machine, never by way of a proxy
        return URLSession(configuration: plain)
    }()

    private let direct: Target?  // --port
    private var linked = false  // a link has arrived, so this was no Dock launch
    private var showing: Target?  // the cockpit the window is on: its health said kcgx
    private var loaded = false  // and the cockpit's page is in the window
    private var asked = 0  // counts shows and starts, so a late answer to an old one is dropped
    private var ended = false  // the page shut the cockpit down itself
    private var launcher: Process?  // bin/kcgx, while it is starting the cockpit
    private var leaving = false  // Quit was asked for while it was, and waits for it

    init(direct: Target?) {
        self.direct = direct
    }

    // -- the app ---------------------------------------------------------------

    func applicationWillFinishLaunching(_ notification: Notification) {
        NSWindow.allowsAutomaticWindowTabbing = false
        NSApp.setActivationPolicy(.regular)
        NSApp.mainMenu = menus()
        build()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        reveal()
        if let direct {
            show(direct)
        } else if openedByLink() {
            // The link has reached application(_:open:) or is on its way
            // there. Whatever it turns out to ask for, a launch by a link
            // never starts the cockpit.
        } else if notification.userInfo?[NSApplication.launchIsDefaultUserInfoKey] as? Bool ?? true {
            if !linked { start() }
        } else {
            // Opened for something, and a link is the only thing it can be
            // opened for. It should be here by now; if none comes after
            // all, this was an ordinary launch.
            DispatchQueue.main.asyncAfter(deadline: .now() + 1) { if !self.linked { self.start() } }
        }
    }

    /// Whether what opened the app was a link. While the app finishes
    /// launching, the current Apple event is the one that launched it, and
    /// a link comes as a GetURL.
    private func openedByLink() -> Bool {
        guard let event = NSAppleEventManager.shared().currentAppleEvent else { return false }
        return event.eventClass == AEEventClass(kInternetEventClass) && event.eventID == AEEventID(kAEGetURL)
    }

    func application(_ application: NSApplication, open urls: [URL]) {
        // Even a link that is refused means this was not a Dock launch: a
        // web page must not be able to start the cockpit with a bad link.
        linked = true
        guard let link = urls.first, let target = Target(link: link) else {
            NSLog("KCGX: refused %@", urls.first?.absoluteString ?? "a link")
            reveal()
            if showing == nil { say("THAT IS NOT A LINK KCGX OPENS.\n\nCOMMAND-R STARTS THE COCKPIT.") }
            return
        }
        show(target)
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows: Bool) -> Bool {
        reveal()  // a click on the Dock icon
        return true
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    /// Quit stops the cockpit, unless the page has stopped it already.
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if let showing, !ended { stop(showing) }
        guard launcher != nil else { return .terminateNow }
        // The launcher is still starting a cockpit. There is nothing to
        // stop until it has, and left to itself that cockpit would come up
        // playing with no window. So Quit waits for the launcher, and
        // start() then stops what it started.
        leaving = true
        say("STOPPING THE COCKPIT")
        // The launcher gives a server 20 s to answer (kcgx.launcher). Past
        // that something is stuck, and Quit still has to quit.
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) {
            if let launcher = self.launcher, launcher.isRunning { launcher.terminate() }
            self.leave()
        }
        return .terminateLater
    }

    /// Ask the cockpit on `target`'s port to shut down, and give it 2 s to answer.
    private func stop(_ target: Target) {
        var request = URLRequest(url: target.api("shutdown"), timeoutInterval: 2)
        request.httpMethod = "POST"
        let answered = DispatchSemaphore(value: 0)
        session.dataTask(with: request) { _, _, _ in answered.signal() }.resume()
        _ = answered.wait(timeout: .now() + 2)
    }

    /// Let a Quit that was waiting for the launcher go ahead.
    private func leave() {
        guard leaving else { return }
        leaving = false
        NSApp.reply(toApplicationShouldTerminate: true)
    }

    // -- the window ------------------------------------------------------------

    private func build() {
        let settings = WKWebViewConfiguration()
        // The page keeps nothing in the browser (every setting is the
        // server's), so nothing of it is kept on disk here either.
        settings.websiteDataStore = .nonPersistent()
        settings.userContentController.add(self, name: "kcgx")
        web = WKWebView(frame: NSRect(x: 0, y: 0, width: 1440, height: 900), configuration: settings)
        web.navigationDelegate = self
        web.underPageBackgroundColor = .black
        if web.responds(to: NSSelectorFromString("_setDrawsBackground:")) {
            web.setValue(false, forKey: "drawsBackground")  // black, not white, until the page paints
        }
        if #available(macOS 13.3, *) { web.isInspectable = true }

        window = NSWindow(
            contentRect: web.frame, styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        window.title = "KCGX"
        window.appearance = NSAppearance(named: .darkAqua)
        window.backgroundColor = .black
        window.isReleasedWhenClosed = false
        window.contentMinSize = NSSize(width: 390, height: 480)
        window.contentView = web
        window.delegate = self
        if !window.setFrameUsingName("KCGXCockpit") { window.center() }  // where it was last time
        window.setFrameAutosaveName("KCGXCockpit")

        titleWatch = web.observe(\.title, options: [.new]) { [weak self] web, _ in
            DispatchQueue.main.async {
                let title = web.title ?? ""
                self?.window.title = title.isEmpty ? "KCGX" : title
            }
        }
    }

    private func menus() -> NSMenu {
        func item(_ title: String, _ action: Selector, _ key: String = "",
                  _ with: NSEvent.ModifierFlags = .command, target: AnyObject? = nil) -> NSMenuItem {
            let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
            item.keyEquivalentModifierMask = with
            item.target = target
            return item
        }
        func menu(_ title: String, _ items: [NSMenuItem]) -> NSMenuItem {
            let top = NSMenuItem()
            top.submenu = NSMenu(title: title)
            items.forEach { top.submenu?.addItem($0) }
            return top
        }
        let bar = NSMenu()
        bar.addItem(menu("KCGX", [
            item("Hide KCGX", #selector(NSApplication.hide(_:)), "h"),
            .separator(),
            item("Quit KCGX", #selector(NSApplication.terminate(_:)), "q"),
        ]))
        // Without these the airport search cannot paste: the keys are the menu's.
        bar.addItem(menu("Edit", [
            item("Cut", #selector(NSText.cut(_:)), "x"),
            item("Copy", #selector(NSText.copy(_:)), "c"),
            item("Paste", #selector(NSText.paste(_:)), "v"),
            item("Select All", #selector(NSText.selectAll(_:)), "a"),
        ]))
        bar.addItem(menu("View", [
            item("Reload", #selector(reload(_:)), "r", target: self),
            item("Enter Full Screen", #selector(NSWindow.toggleFullScreen(_:)), "f", [.command, .control]),
        ]))
        let windows = menu("Window", [
            item("Minimize", #selector(NSWindow.performMiniaturize(_:)), "m"),
            item("Zoom", #selector(NSWindow.performZoom(_:))),
            item("Close", #selector(NSWindow.performClose(_:)), "w"),
        ])
        bar.addItem(windows)
        NSApp.windowsMenu = windows.submenu
        return bar
    }

    /// The red button hides the app, as Hide does: the cockpit plays on, and
    /// the Dock icon brings the window back.
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        NSApp.hide(nil)
        return false
    }

    private func reveal() {
        NSApp.unhide(nil)
        if window.isMiniaturized { window.deminiaturize(nil) }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    /// Words in the window, when there is no cockpit to show in it.
    private func say(_ text: String) {
        showing = nil
        loaded = false
        let safe = text.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
        web.loadHTMLString("""
            <!doctype html><meta charset="utf-8">
            <body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#000;color:#c4f0ff;\
            font:13px/1.6 ui-monospace,Menlo,monospace;letter-spacing:0.06em">
            <pre style="font:inherit;white-space:pre-wrap;margin:24px;max-width:90ch">\(safe)</pre>
            """, baseURL: nil)
    }

    // -- showing a cockpit -----------------------------------------------------

    /// Show the cockpit on `target`'s port, once its health says it is one.
    /// If its page is already in the window only the fragment is set, so
    /// the page keeps its socket.
    private func show(_ target: Target) {
        reveal()
        asked += 1
        let mine = asked
        let request = URLRequest(
            url: target.api("health"), cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 2)
        session.dataTask(with: request) { data, response, _ in
            let body = data.flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]
            let kcgx = (response as? HTTPURLResponse)?.statusCode == 200
                && body?["app"] as? String == "kcgx" && body?["ok"] as? Bool == true
            DispatchQueue.main.async { if mine == self.asked { self.checked(target, kcgx) } }
        }.resume()
    }

    private func checked(_ target: Target, _ kcgx: Bool) {
        guard kcgx else {
            NSLog("KCGX: nothing on port %d says it is kcgx", target.port)
            if showing == nil {
                say("NO KCGX COCKPIT ANSWERS ON PORT \(target.port).\n\nCOMMAND-R STARTS THE COCKPIT.")
            }
            return
        }
        if showing?.port == target.port, loaded {
            // legal() left no quote and no backslash, so this is one string.
            if !target.fragment.isEmpty { web.evaluateJavaScript("location.hash = \"\(target.fragment)\"") }
            return
        }
        showing = target
        loaded = false
        NSLog("KCGX: loading %@", target.page.absoluteString)
        web.load(URLRequest(url: target.page))
    }

    /// Opened with no link: start the cockpit as `kcgx --no-open` would,
    /// then show the one it recorded. One launcher at a time: a second
    /// beside the first (Reload while it says STARTING) could start a
    /// second server.
    private func start() {
        guard launcher == nil else { return }
        asked += 1
        let mine = asked
        let repo = Bundle.main.object(forInfoDictionaryKey: "KCGXRepo") as? String ?? ""
        let script = URL(fileURLWithPath: repo).appendingPathComponent("bin/kcgx")
        guard !repo.isEmpty, FileManager.default.isExecutableFile(atPath: script.path) else {
            say("NO KCGX AT \(script.path)\n\nRUN setup.sh AGAIN TO REBUILD THIS WINDOW.")
            return
        }
        say("STARTING THE COCKPIT")
        let process = Process()
        launcher = process
        process.executableURL = script
        process.arguments = ["--no-open"]
        var environment = ProcessInfo.processInfo.environment
        if let path = Bundle.main.object(forInfoDictionaryKey: "KCGXPath") as? String, !path.isEmpty {
            environment["PATH"] = path
        }
        process.environment = environment
        let output = Pipe()
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = output
        process.standardError = output
        DispatchQueue.global(qos: .userInitiated).async {
            var said = ""
            var status: Int32 = -1
            do {
                try process.run()
                // The launcher's own words. The server it leaves running
                // writes to its log, not here, so this ends with the launcher.
                said = String(decoding: output.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
                process.waitUntilExit()
                status = process.terminationStatus
            } catch {
                said = error.localizedDescription
            }
            DispatchQueue.main.async {
                self.launcher = nil
                if self.leaving {  // Quit has been waiting for this
                    if status == 0, let target = self.recorded() { self.stop(target) }
                    self.leave()
                } else if mine == self.asked {
                    self.started(status, said)
                }
            }
        }
    }

    private func started(_ status: Int32, _ said: String) {
        let words = said.trimmingCharacters(in: .whitespacesAndNewlines)
        guard status == 0 else {
            say((words.isEmpty ? "kcgx: could not start the cockpit (\(status))" : words) + "\n\nCOMMAND-R TRIES AGAIN.")
            return
        }
        guard let target = recorded() else {
            say("kcgx: the cockpit started, but did not record where.\n\(words)\n\nCOMMAND-R TRIES AGAIN.")
            return
        }
        show(target)
    }

    /// The port in the launcher's server.json, which is kept beside the
    /// remembered airport (kcgx.state, kcgx.launcher).
    private func recorded() -> Target? {
        let moved = ProcessInfo.processInfo.environment["KCGX_STATE_PATH"] ?? ""
        let folder = moved.isEmpty
            ? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/state/kcgx")
            : URL(fileURLWithPath: moved).deletingLastPathComponent()
        guard let data = try? Data(contentsOf: folder.appendingPathComponent("server.json")),
              let info = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let port = info["port"] as? Int else { return nil }
        return Target(port: String(port))
    }

    /// View > Reload. With no cockpit in the window, it starts one, unless
    /// one is being started already.
    @objc private func reload(_ sender: Any?) {
        if showing != nil {
            loaded = false  // so that a reload that fails says so
            web.reload()
        } else {
            start()
        }
    }

    // -- what the page may do ---------------------------------------------------

    /// The server's own pages: this machine, the port being shown.
    private func ours(_ url: URL?) -> Bool {
        guard let url, let showing else { return false }
        return url.scheme == "http" && url.host == host && url.port == showing.port
    }

    /// The cockpit itself, which is the page that reads a fragment.
    private func cockpit(_ url: URL?) -> Bool { ours(url) && url?.path == "/" }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        let url = action.request.url
        if ours(url) {
            if action.targetFrame == nil {  // it asked for a new window: there is one window
                web.load(action.request)
                return decisionHandler(.cancel)
            }
            return decisionHandler(.allow)
        }
        if url?.absoluteString == "about:blank" {  // say()'s words
            return decisionHandler(.allow)
        }
        // Anywhere else is not for this window. A link the user pressed
        // goes to their browser; anything else goes nowhere.
        if let url, action.navigationType == .linkActivated, url.scheme == "http" || url.scheme == "https" {
            NSWorkspace.shared.open(url)
        }
        decisionHandler(.cancel)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        loaded = cockpit(webView.url)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        let failure = error as NSError
        let failed = failure.userInfo[NSURLErrorFailingURLErrorKey] as? URL
        guard let showing, !loaded, ours(failed), failure.code != NSURLErrorCancelled else { return }
        NSLog("KCGX: %@ did not load: %@", showing.home.absoluteString, failure.localizedDescription)
        say("THE COCKPIT ON PORT \(showing.port) DID NOT LOAD.\n\(failure.localizedDescription)\n\nCOMMAND-R STARTS IT.")
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        loaded = false
        if let showing { web.load(URLRequest(url: showing.home)) }  // without the fragment: that was for once
    }

    /// The page says "ended" once it has shut the cockpit down (main.js).
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        let origin = message.frameInfo.securityOrigin
        guard let showing, message.frameInfo.isMainFrame, origin.host == host, origin.port == showing.port,
              message.body as? String == "ended" else { return }
        ended = true
        NSApp.terminate(nil)
    }
}

// -- main ------------------------------------------------------------------------

func argument(after flag: String) -> String? {
    let arguments = CommandLine.arguments
    guard let at = arguments.firstIndex(of: flag) else { return nil }
    return at + 1 < arguments.count ? arguments[at + 1] : ""
}

if let link = argument(after: "--check") {
    guard let url = URL(string: link), let target = Target(link: url) else {
        FileHandle.standardError.write(Data("refused\n".utf8))
        exit(1)
    }
    print(target.page.absoluteString)
    exit(0)
}

var direct: Target?
if let port = argument(after: "--port") {
    direct = Target(port: port)
    if direct == nil {
        FileHandle.standardError.write(Data("KCGX: --port takes a whole number from 1024 to 65535\n".utf8))
        exit(2)
    }
}

let cockpit = Cockpit(direct: direct)
NSApplication.shared.delegate = cockpit
NSApplication.shared.run()
