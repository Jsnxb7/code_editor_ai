import { useEffect, useRef } from "react";
import { Terminal } from "xterm";
import { FitAddon } from "xterm-addon-fit";
import "xterm/css/xterm.css";
import { getSocket } from "../socket";

export default function TerminalView({ terminalId, project, active, registerWriter }) {
  const hostRef = useRef(null);
  const termRef = useRef(null);
  const fitRef = useRef(null);
  const readyRef = useRef(false);
  const queueRef = useRef([]);
  const disposedRef = useRef(false);
  const frameRef = useRef(null);

  useEffect(() => {
    disposedRef.current = false;
    readyRef.current = false;
    queueRef.current = [];
    const term = new Terminal({
      cursorBlink: true,
      convertEol: false,
      scrollback: 10000,
      fontFamily: "'JetBrains Mono', 'Cascadia Code', Consolas, monospace",
      fontSize: 13,
      theme: {
        background: "#0d0e11",
        foreground: "#e8eaf0",
        cursor: "#f5a623",
        selectionBackground: "#2a2d38",
        black: "#0d0e11",
        red: "#f56060",
        green: "#52d68a",
        yellow: "#f5c842",
        blue: "#4dd9ec",
        magenta: "#c792ea",
        cyan: "#4dd9ec",
        white: "#e8eaf0",
      },
    });
    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(hostRef.current);
    termRef.current = term;
    fitRef.current = fitAddon;

    const socket = getSocket();

    const fitAndNotify = () => {
      if (disposedRef.current || !hostRef.current?.isConnected || hostRef.current.clientWidth < 2 || hostRef.current.clientHeight < 2) return;
      try {
        fitAddon.fit();
        socket.emit("terminal:resize", { terminalId, cols: term.cols, rows: term.rows });
      } catch {
        /* panel may be hidden/mid-transition; ignore */
      }
    };
    fitRef.current.fitAndNotify = fitAndNotify;

    const onData = (payload) => {
      if (payload.terminalId !== terminalId) return;
      term.write(payload.data);
    };
    const onReady = (payload) => {
      if (payload.terminalId !== terminalId) return;
      readyRef.current = true;
      queueRef.current.forEach((text) => socket.emit("terminal:input", { terminalId, data: text }));
      queueRef.current = [];
      frameRef.current = requestAnimationFrame(fitAndNotify);
    };
    const onExit = (payload) => {
      if (payload.terminalId !== terminalId) return;
      term.write("\r\n\x1b[90m[process exited]\x1b[0m\r\n");
    };
    const onErr = (payload) => {
      if (payload.terminalId !== terminalId) return;
      term.write(`\r\n\x1b[31m[terminal error] ${payload.message}\x1b[0m\r\n`);
    };

    socket.on("terminal:data", onData);
    socket.on("terminal:ready", onReady);
    socket.on("terminal:exit", onExit);
    socket.on("terminal:error", onErr);

    const sendCreate = () => socket.emit("terminal:create", { terminalId, project });
    if (socket.connected) sendCreate();
    socket.on("connect", sendCreate);

    const disposeInput = term.onData((data) => {
      socket.emit("terminal:input", { terminalId, data });
    });

    registerWriter(terminalId, (text) => {
      if (readyRef.current) {
        socket.emit("terminal:input", { terminalId, data: text });
      } else {
        queueRef.current.push(text);
      }
    });

    return () => {
      disposedRef.current = true;
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      socket.emit("terminal:dispose", { terminalId });
      socket.off("terminal:data", onData);
      socket.off("terminal:ready", onReady);
      socket.off("terminal:exit", onExit);
      socket.off("terminal:error", onErr);
      socket.off("connect", sendCreate);
      disposeInput.dispose();
      term.dispose();
      termRef.current = null;
      fitRef.current = null;
      readyRef.current = false;
      queueRef.current = [];
      registerWriter(terminalId, null);
    };
  }, [terminalId, project, registerWriter]);

  useEffect(() => {
    if (!active || !fitRef.current) return;
    frameRef.current = requestAnimationFrame(() => {
      if (!disposedRef.current) fitRef.current?.fitAndNotify?.();
    });
    return () => { if (frameRef.current !== null) cancelAnimationFrame(frameRef.current); };
  }, [active, terminalId]);

  useEffect(() => {
    const handle = () => {
      if (!active) return;
      fitRef.current?.fitAndNotify?.();
    };
    window.addEventListener("resize", handle);

    let observer;
    if (hostRef.current && "ResizeObserver" in window) {
      observer = new ResizeObserver(() => handle());
      observer.observe(hostRef.current);
    }
    return () => {
      window.removeEventListener("resize", handle);
      observer?.disconnect();
    };
  }, [active]);

  return <div ref={hostRef} className="terminal-host" style={{ display: active ? "block" : "none" }} />;
}
