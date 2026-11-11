#!/usr/bin/env node
// Copyright (C) 2026 remrekoc. SPDX-License-Identifier: GPL-3.0-or-later (see LICENSE)
// Drive the local site in headless Chrome over the DevTools protocol, to check interactions.
//   node build/drive.mjs <url> '<steps json>' [width height]
// Steps: {"wait":ms} {"eval":"js"} {"log":"js expression"} {"click":"css selector"} {"hover":"css selector"}
//        {"mouse":[x,y]} {"drag":[x0,y0,x1,y1]} {"key":"Escape"} {"shot":"path.png"}
// Console errors and uncaught exceptions are printed.
import { spawn } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const [url, stepsJson, w = "1440", h = "900"] = process.argv.slice(2);
const steps = JSON.parse(stepsJson);
const prof = process.env.DRIVE_PROFILE || resolve(dirname(fileURLToPath(import.meta.url)), ".chrome-cdp-harita-ray");
mkdirSync(prof, { recursive: true });
const port = 9300 + Math.floor(Math.random() * 500);
const chrome = spawn(CHROME, ["--headless=new", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--hide-scrollbars", `--user-data-dir=${prof}`, `--remote-debugging-port=${port}`,
  "--force-device-scale-factor=1", `--window-size=${w},${h}`, "about:blank"], { stdio: "ignore" });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let ws, id = 0;
const pending = new Map();
const send = (method, params = {}) => new Promise((ok, no) => { const i = ++id; pending.set(i, { ok, no }); ws.send(JSON.stringify({ id: i, method, params })); });
try {
  let target;
  for (let i = 0; i < 50 && !target; i++) {
    await sleep(200);
    try { target = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find(t => t.type === "page"); } catch {}
  }
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener("open", r));
  ws.addEventListener("message", ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.no(new Error(m.error.message)) : p.ok(m.result); }
    if (m.method === "Runtime.exceptionThrown") console.log("EXCEPTION", m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
    if (m.method === "Runtime.consoleAPICalled" && ["error", "warning"].includes(m.params.type)) console.log("CONSOLE", m.params.type, m.params.args.map(a => a.value ?? a.description).join(" "));
  });
  await send("Runtime.enable"); await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: +w, height: +h, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url });
  await sleep(2500);
  const evalJs = async js => { const r = await send("Runtime.evaluate", { expression: js, awaitPromise: true, returnByValue: true }); if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || "eval failed"); return r.result.value; };
  const center = async sel => { const c = await evalJs(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null; const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()`); if (!c) throw new Error("no element " + sel); return c; };
  const mouse = (type, x, y, extra = {}) => send("Input.dispatchMouseEvent", { type, x, y, button: "left", clickCount: 1, ...extra });
  for (const s of steps) {
    if (s.wait) await sleep(s.wait);
    if (s.eval) await evalJs(s.eval);
    if (s.log) console.log("LOG", JSON.stringify(await evalJs(s.log)));
    if (s.click) { const [x, y] = await center(s.click); await mouse("mouseMoved", x, y, { button: "none" }); await mouse("mousePressed", x, y); await mouse("mouseReleased", x, y); }
    if (s.hover) { const [x, y] = await center(s.hover); await mouse("mouseMoved", x, y, { button: "none" }); }
    if (s.mouse) await mouse("mouseMoved", s.mouse[0], s.mouse[1], { button: "none" });
    if (s.drag) {
      const [x0, y0, x1, y1] = s.drag;
      await mouse("mouseMoved", x0, y0, { button: "none" }); await mouse("mousePressed", x0, y0);
      for (let i = 1; i <= 10; i++) { await mouse("mouseMoved", x0 + (x1 - x0) * i / 10, y0 + (y1 - y0) * i / 10, { buttons: 1 }); await sleep(16); }
      await mouse("mouseReleased", x1, y1);
    }
    if (s.key) { await send("Input.dispatchKeyEvent", { type: "keyDown", key: s.key }); await send("Input.dispatchKeyEvent", { type: "keyUp", key: s.key }); }
    if (s.shot) { const r = await send("Page.captureScreenshot", { format: "png" }); writeFileSync(s.shot, Buffer.from(r.data, "base64")); console.log("SHOT", s.shot); }
  }
} catch (e) { console.log("ERROR", e.message); }
finally { try { ws && ws.close(); } catch {} chrome.kill(); await sleep(300); rmSync(prof, { recursive: true, force: true }); }
