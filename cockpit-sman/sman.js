/* sman Cockpit plugin — AI Sysadmin dashboard + chat */
(function () {
    "use strict";

    const SMAND_HOST = "127.0.0.1";
    const SMAND_PORT = 9876;
    const REFRESH_INTERVAL = 30000; // 30s dashboard refresh

    // --- State ---
    const CHAT_STORAGE_KEY = "sman-chat-history";
    let ws = null;
    let chatHistory = loadChatHistory();
    let refreshTimer = null;

    function loadChatHistory() {
        try {
            return JSON.parse(localStorage.getItem(CHAT_STORAGE_KEY)) || [];
        } catch { return []; }
    }

    function saveChatHistory() {
        // Keep last 100 messages to avoid bloating storage
        if (chatHistory.length > 100) chatHistory = chatHistory.slice(-100);
        try {
            localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(chatHistory));
        } catch { /* storage full, ignore */ }
    }

    // --- Helpers ---
    function el(tag, attrs, ...children) {
        const e = document.createElement(tag);
        if (attrs) {
            for (const [k, v] of Object.entries(attrs)) {
                if (k === "className") e.className = v;
                else if (k.startsWith("on")) e.addEventListener(k.slice(2).toLowerCase(), v);
                else e.setAttribute(k, v);
            }
        }
        for (const c of children) {
            if (typeof c === "string") e.appendChild(document.createTextNode(c));
            else if (c) e.appendChild(c);
        }
        return e;
    }

    function badge(text, color) {
        return el("span", { className: `sman-badge ${color}` }, text);
    }

    function statusColor(state) {
        if (state === "active" || state === "running") return "green";
        if (state === "failed") return "red";
        return "yellow";
    }

    function severityColor(sev) {
        if (sev === "CRITICAL" || sev === "EMERGENCY") return "red";
        if (sev === "WARNING") return "yellow";
        return "green";
    }

    function escapeHtml(s) {
        const d = document.createElement("div");
        d.textContent = s;
        return d.innerHTML;
    }

    function formatTimestamp(ts) {
        if (!ts) return "";
        try {
            const d = new Date(ts);
            return d.toLocaleTimeString();
        } catch {
            return ts;
        }
    }

    // --- API calls via cockpit.http ---
    function smandHttp(path) {
        return new Promise((resolve, reject) => {
            const http = cockpit.http(SMAND_PORT, { address: SMAND_HOST });
            http.get(path)
                .then(data => {
                    try { resolve(JSON.parse(data)); }
                    catch { resolve(data); }
                })
                .catch(reject);
        });
    }

    // --- Build Layout ---
    function buildApp() {
        const app = document.getElementById("app");
        app.innerHTML = "";

        // Top bar
        const topbar = el("div", { className: "sman-topbar" },
            el("h1", null, "sman", el("span", null, "AI Sysadmin")),
            el("div", { className: "sman-status", id: "conn-status" },
                el("span", { className: "sman-status-dot disconnected", id: "conn-dot" }),
                el("span", null, "connecting...")
            )
        );

        // Dashboard panel
        const dashboard = el("div", { className: "sman-dashboard", id: "dashboard" },
            el("div", { className: "sman-cards", id: "summary-cards" }),
            el("div", { id: "service-section" }),
            el("div", { id: "ssh-section" }),
            el("div", { id: "disk-section" }),
            el("div", { id: "alert-section" })
        );

        // Chat panel
        const chat = el("div", { className: "sman-chat" },
            el("div", { className: "sman-chat-header" }, "Ask sman"),
            el("div", { className: "sman-chat-messages", id: "chat-messages" }),
            el("div", { className: "sman-chat-input" },
                el("input", {
                    type: "text",
                    id: "chat-input",
                    placeholder: "Ask about your system...",
                    onKeydown: function (e) { if (e.key === "Enter") sendMessage(); }
                }),
                el("button", { onClick: sendMessage }, "Send")
            )
        );

        app.appendChild(topbar);
        app.appendChild(dashboard);
        app.appendChild(chat);

        // Restore chat or show welcome
        if (chatHistory.length > 0) {
            restoreChatHistory();
        } else {
            appendChatMessage("assistant",
                "Hey! I'm <strong>sman</strong>, your AI sysadmin. Ask me anything about this system.\n\n" +
                "Try: <em>\"show failed services\"</em>, <em>\"check disk space\"</em>, or <em>\"who's been trying to SSH in?\"</em>"
            );
        }
    }

    // --- Dashboard Rendering ---
    function renderSummaryCards(data) {
        const container = document.getElementById("summary-cards");
        container.innerHTML = "";

        const cards = [
            { title: "Hostname", value: data.hostname || "—", subtitle: data.os_name || "" },
            { title: "Uptime", value: data.uptime || "—", subtitle: "" },
            { title: "Services", value: `${data.active_count || 0}`, subtitle: `${data.total_services || 0} watched · ${data.failed_count || 0} failed`, color: (data.failed_count > 0) ? "text-red" : "text-green" },
            { title: "SSH Attacks (24h)", value: `${data.ssh?.total_failures || 0}`, subtitle: `${data.ssh?.unique_ips || 0} unique IPs`, color: (data.ssh?.total_failures > 50) ? "text-red" : (data.ssh?.total_failures > 10) ? "text-yellow" : "text-green" },
        ];

        for (const c of cards) {
            const card = el("div", { className: "sman-card" },
                el("h4", null, c.title),
                el("div", { className: `sman-value ${c.color || ""}` }, c.value),
                el("div", { className: "sman-subtitle" }, c.subtitle)
            );
            container.appendChild(card);
        }
    }

    function renderServiceGrid(services) {
        const section = document.getElementById("service-section");
        section.innerHTML = "";

        if (!services || services.length === 0) return;

        const header = el("h3", { style: "font-size:13px;text-transform:uppercase;letter-spacing:0.5px;color:var(--pf-t--global--text--color--subtle);margin:0 0 8px 0;" }, "Watched Services");
        const grid = el("div", { className: "sman-service-grid" });

        for (const svc of services) {
            const color = statusColor(svc.active_state);
            const item = el("div", { className: "sman-service-item", onClick: () => askAboutService(svc.name) },
                el("span", { className: `sman-service-dot`, style: `background:var(--sman-${color})` }),
                el("div", null,
                    el("div", { className: "sman-service-name" }, svc.name),
                    el("div", { className: "sman-service-mem" }, svc.memory || "")
                )
            );
            grid.appendChild(item);
        }

        const tip = el("div", { className: "sman-tip" },
            el("span", null, "Click a service to ask sman about it. CLI: "),
            el("code", null, "systemctl status <service>")
        );

        section.appendChild(header);
        section.appendChild(grid);
        section.appendChild(tip);
    }

    function renderSSHTable(ssh) {
        const section = document.getElementById("ssh-section");
        section.innerHTML = "";

        if (!ssh || !ssh.top_offenders || ssh.top_offenders.length === 0) return;

        const block = el("div", { className: "sman-section" },
            el("h3", null, "SSH Brute Force — Top Offenders")
        );

        const table = el("table");
        const thead = el("tr", null,
            el("th", null, "IP Address"),
            el("th", null, "Attempts"),
            el("th", null, "Last Seen")
        );
        table.appendChild(thead);

        for (const entry of ssh.top_offenders.slice(0, 10)) {
            const row = el("tr", null,
                el("td", { className: "font-mono" }, entry.ip || entry[0] || "—"),
                el("td", { className: "text-red font-mono" }, String(entry.count || entry[1] || "—")),
                el("td", { className: "text-dim" }, formatTimestamp(entry.last_seen || entry[2] || ""))
            );
            table.appendChild(row);
        }

        block.appendChild(table);

        const tip = el("div", { className: "sman-tip" },
            el("span", null, "Block an IP: "),
            el("code", null, "sudo firewall-cmd --add-rich-rule='rule family=ipv4 source address=<IP> reject' --permanent")
        );
        block.appendChild(tip);

        section.appendChild(block);
    }

    function renderDiskTable(disks) {
        const section = document.getElementById("disk-section");
        section.innerHTML = "";

        if (!disks || disks.length === 0) return;

        const block = el("div", { className: "sman-section" },
            el("h3", null, "Disk Space")
        );

        const table = el("table");
        const thead = el("tr", null,
            el("th", null, "Mount"),
            el("th", null, "Size"),
            el("th", null, "Used"),
            el("th", null, "Avail"),
            el("th", null, "Use%")
        );
        table.appendChild(thead);

        for (const d of disks) {
            const pct = parseInt(d.use_percent || d.percent || "0");
            const color = pct >= 90 ? "text-red" : pct >= 80 ? "text-yellow" : "text-green";
            const row = el("tr", null,
                el("td", { className: "font-mono" }, d.mount || d.mounted_on || "—"),
                el("td", null, d.size || "—"),
                el("td", null, d.used || "—"),
                el("td", null, d.avail || d.available || "—"),
                el("td", { className: `font-mono ${color}` }, (d.use_percent || d.percent || "—") + (typeof d.use_percent === "number" ? "%" : ""))
            );
            table.appendChild(row);
        }

        block.appendChild(table);

        const tip = el("div", { className: "sman-tip" },
            el("span", null, "Find large files: "),
            el("code", null, "du -sh /* 2>/dev/null | sort -rh | head -10")
        );
        block.appendChild(tip);

        section.appendChild(block);
    }

    function renderAlerts(alerts) {
        const section = document.getElementById("alert-section");
        section.innerHTML = "";

        if (!alerts || alerts.length === 0) return;

        const block = el("div", { className: "sman-section" },
            el("h3", null, "Recent Alerts")
        );

        const table = el("table");
        const thead = el("tr", null,
            el("th", null, "Time"),
            el("th", null, "Severity"),
            el("th", null, "Source"),
            el("th", null, "Message")
        );
        table.appendChild(thead);

        for (const a of alerts.slice(0, 10)) {
            const row = el("tr", null,
                el("td", { className: "text-dim" }, formatTimestamp(a.timestamp)),
                el("td", null, badge(a.severity || "INFO", severityColor(a.severity))),
                el("td", { className: "font-mono" }, a.source || "—"),
                el("td", null, a.message || "—")
            );
            table.appendChild(row);
        }

        block.appendChild(table);
        section.appendChild(block);
    }

    async function refreshDashboard() {
        try {
            const data = await smandHttp("/api/monitors");

            const ssh = data.ssh_recent || { total_failures: 0, unique_ips: 0, top_offenders: [] };
            const disks = data.disk_space || [];
            const services = data.services || [];
            const alerts = data.alerts || [];

            const active = services.filter(s => s.active_state === "active").length;
            const failed = services.filter(s => s.active_state === "failed").length;

            // Get system info from /api/status
            let hostname = "—", uptime = "—", os_name = "";
            try {
                const status = await smandHttp("/api/status");
                // Parse from system overview text if available
                if (status.system) {
                    const lines = status.system.split("\n");
                    for (const line of lines) {
                        if (line.includes("hostname")) hostname = line.split(":").pop().trim();
                    }
                }
            } catch { /* use defaults */ }

            // Try cockpit for hostname
            try {
                hostname = cockpit.transport.host || hostname;
            } catch { /* use what we have */ }

            renderSummaryCards({
                hostname, uptime, os_name,
                active_count: active,
                failed_count: failed,
                total_services: services.length,
                ssh
            });
            renderServiceGrid(services);
            renderSSHTable(ssh);
            renderDiskTable(disks);
            renderAlerts(alerts);

            setConnected(true);
        } catch (err) {
            console.error("Dashboard refresh failed:", err);
            setConnected(false);
        }
    }

    // --- Connection Status ---
    function setConnected(connected) {
        const dot = document.getElementById("conn-dot");
        const status = document.getElementById("conn-status");
        if (!dot || !status) return;

        dot.className = `sman-status-dot ${connected ? "connected" : "disconnected"}`;
        status.lastChild.textContent = connected ? "smand connected" : "smand disconnected";
    }

    // --- Chat ---
    function appendChatMessage(role, content, save = true) {
        const container = document.getElementById("chat-messages");
        const msg = el("div", { className: `sman-msg ${role}` });
        msg.innerHTML = formatChatContent(content);
        container.appendChild(msg);
        container.scrollTop = container.scrollHeight;
        if (save && content) {
            chatHistory.push({ role, content });
            saveChatHistory();
        }
        return msg;
    }

    function restoreChatHistory() {
        if (chatHistory.length === 0) return;
        const container = document.getElementById("chat-messages");
        container.innerHTML = "";
        for (const entry of chatHistory) {
            const msg = el("div", { className: `sman-msg ${entry.role}` });
            msg.innerHTML = formatChatContent(entry.content);
            container.appendChild(msg);
        }
        container.scrollTop = container.scrollHeight;
    }

    function formatChatContent(content) {
        if (!content) return "";
        let html = escapeHtml(content);

        // Convert markdown-style code blocks
        html = html.replace(/```([\s\S]*?)```/g, (_, code) => `<pre>${code.trim()}</pre>`);

        // Convert inline code
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

        // Convert command displays (lines starting with $)
        html = html.replace(/^(\$ .+)$/gm, '<span class="sman-cmd">$1</span>');

        // Allow explicit HTML tags we inserted
        html = html.replace(/&lt;strong&gt;/g, "<strong>").replace(/&lt;\/strong&gt;/g, "</strong>");
        html = html.replace(/&lt;em&gt;/g, "<em>").replace(/&lt;\/em&gt;/g, "</em>");
        html = html.replace(/&lt;code&gt;/g, "<code>").replace(/&lt;\/code&gt;/g, "</code>");
        html = html.replace(/&lt;pre&gt;/g, "<pre>").replace(/&lt;\/pre&gt;/g, "</pre>");
        html = html.replace(/&lt;br&gt;/g, "<br>");

        // Newlines to <br>
        html = html.replace(/\n/g, "<br>");

        return html;
    }

    function sendMessage() {
        const input = document.getElementById("chat-input");
        const text = input.value.trim();
        if (!text) return;

        input.value = "";
        appendChatMessage("user", text);

        // Create assistant message placeholder (don't save empty placeholder)
        const assistantMsg = appendChatMessage("assistant", "", false);
        assistantMsg.innerHTML = '<span class="sman-spinner"></span>';

        // Send via WebSocket
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ message: text }));
            currentAssistantMsg = assistantMsg;
            assistantBuffer = "";
        } else {
            // Fallback to REST API
            sendViaRest(text, assistantMsg);
        }
    }

    let currentAssistantMsg = null;
    let assistantBuffer = "";

    async function sendViaRest(text, msgEl) {
        try {
            const http = cockpit.http(SMAND_PORT, { address: SMAND_HOST });
            const resp = await http.request({
                method: "POST",
                path: "/api/ask",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: text })
            });
            const data = JSON.parse(resp);
            msgEl.innerHTML = formatChatContent(data.response || "No response.");
        } catch (err) {
            msgEl.innerHTML = formatChatContent("Failed to reach smand. Is the daemon running?\n\n`sudo systemctl start smand`");
        }
        const container = document.getElementById("chat-messages");
        container.scrollTop = container.scrollHeight;
    }

    function askAboutService(name) {
        const input = document.getElementById("chat-input");
        input.value = `What's the status of ${name}? Show me recent logs.`;
        input.focus();
    }

    // --- WebSocket Chat Connection ---
    function connectWebSocket() {
        try {
            ws = new WebSocket(`ws://${SMAND_HOST}:${SMAND_PORT}/api/chat`);

            ws.onopen = () => {
                console.log("sman WebSocket connected");
            };

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);

                if (data.type === "chunk" && currentAssistantMsg) {
                    assistantBuffer += data.content;
                    currentAssistantMsg.innerHTML = formatChatContent(assistantBuffer);
                    const container = document.getElementById("chat-messages");
                    container.scrollTop = container.scrollHeight;
                } else if (data.type === "done") {
                    // Save the completed streamed message
                    if (assistantBuffer) {
                        chatHistory.push({ role: "assistant", content: assistantBuffer });
                        saveChatHistory();
                    }
                    currentAssistantMsg = null;
                    assistantBuffer = "";
                    // Refresh dashboard after agent actions
                    refreshDashboard();
                } else if (data.type === "error") {
                    if (currentAssistantMsg) {
                        currentAssistantMsg.innerHTML = formatChatContent("Error: " + data.content);
                    }
                    currentAssistantMsg = null;
                    assistantBuffer = "";
                }
            };

            ws.onclose = () => {
                console.log("sman WebSocket closed, reconnecting in 5s...");
                setTimeout(connectWebSocket, 5000);
            };

            ws.onerror = (err) => {
                console.error("sman WebSocket error:", err);
            };
        } catch (err) {
            console.error("WebSocket connection failed:", err);
            setTimeout(connectWebSocket, 5000);
        }
    }

    // --- Init ---
    function init() {
        buildApp();
        refreshDashboard();
        connectWebSocket();

        // Periodic refresh
        refreshTimer = setInterval(refreshDashboard, REFRESH_INTERVAL);
    }

    // Wait for DOM
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
