import { createServer } from "./server.js";

const instance = createServer();
const config = instance.getConfig();

instance.server.listen(config.port, config.host, () => {
  console.log(`Bob Node Gateway listening at http://${config.host}:${config.port}`);
  console.log(`Python MCP: ${config.mcpUrl}`);
});

async function shutdown() {
  await instance.close();
  instance.server.close(() => process.exit(0));
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
