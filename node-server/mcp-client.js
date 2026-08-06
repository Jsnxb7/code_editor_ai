import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

function withTimeout(promise, timeoutMs, message) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(message)), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

function normalizeToolResult(result) {
  if (result?.isError) {
    const message = result.content?.map((item) => item.text).filter(Boolean).join("\n");
    throw new Error(message || "MCP tool call failed");
  }
  if (result?.structuredContent !== undefined) return result.structuredContent;
  const text = result?.content?.find((item) => item.type === "text")?.text;
  if (text === undefined) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { text };
  }
}

export class BobMcpClient {
  constructor(getConfig) {
    this.getConfig = getConfig;
    this.client = null;
    this.connecting = null;
    this.connectedUrl = null;
  }

  async connect() {
    const config = this.getConfig();
    if (this.client && this.connectedUrl === config.mcpUrl) return this.client;
    if (this.connecting) return this.connecting;
    this.connecting = (async () => {
      await this.close();
      const client = new Client({ name: "bob-node-gateway", version: "1.0.0" });
      const transport = new StreamableHTTPClientTransport(new URL(config.mcpUrl));
      await withTimeout(
        client.connect(transport),
        15000,
        `Python MCP did not respond at ${config.mcpUrl}`,
      );
      this.client = client;
      this.connectedUrl = config.mcpUrl;
      return client;
    })();
    try {
      return await this.connecting;
    } finally {
      this.connecting = null;
    }
  }

  async run(operation) {
    try {
      const client = await this.connect();
      return await operation(client);
    } catch (error) {
      await this.close();
      throw error;
    }
  }

  async listTools() {
    const result = await this.run((client) => client.listTools());
    return result.tools || [];
  }

  async callTool(name, arguments_ = {}) {
    const result = await this.run((client) =>
      client.callTool({ name, arguments: arguments_ }),
    );
    return normalizeToolResult(result);
  }

  async health() {
    try {
      const tools = await this.listTools();
      return { ok: true, tools: tools.length, url: this.connectedUrl };
    } catch (error) {
      return { ok: false, tools: 0, url: this.getConfig().mcpUrl, error: error.message };
    }
  }

  async close() {
    const client = this.client;
    this.client = null;
    this.connectedUrl = null;
    if (client) {
      try {
        await client.close();
      } catch {
        // Connection is already gone.
      }
    }
  }
}
