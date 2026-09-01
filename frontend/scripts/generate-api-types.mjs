import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import openapiTS, { astToString } from "openapi-typescript";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const schemaUrl = new URL("../openapi.json", import.meta.url);
const outputUrl = new URL("../src/api.generated.ts", import.meta.url);
const mode = process.argv.includes("--check") ? "check" : "write";
const schemaBytes = await readFile(schemaUrl);
const schemaHash = createHash("sha256").update(schemaBytes).digest("hex");
const ast = await openapiTS(schemaUrl);
const generated = `// OpenAPI-SHA256: ${schemaHash}\n${astToString(ast)}`;

if (mode === "write") {
  await writeFile(outputUrl, generated, "utf8");
  console.log(`Generated ${fileURLToPath(outputUrl)} from ${fileURLToPath(schemaUrl)}`);
  process.exit(0);
}

let current = "";
try {
  current = await readFile(outputUrl, "utf8");
} catch {
  console.error(`Missing generated API types: ${fileURLToPath(outputUrl)}`);
  process.exit(1);
}
if (current !== generated) {
  console.error(
    `Generated API types are stale. Run the OpenAPI export and type generation commands in ${frontendRoot}.`
  );
  process.exit(1);
}
console.log("Generated API types are current.");
