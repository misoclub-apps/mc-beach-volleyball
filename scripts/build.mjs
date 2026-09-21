import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
const data = JSON.parse(await readFile("public/data/beach.json", "utf8"));
if (data.schemaVersion !== 1 || !data.players.length || !data.events.length)
  throw new Error(
    "有効なデータがありません。npm run update を実行してください。",
  );
await rm("dist", { recursive: true, force: true });
await mkdir("dist", { recursive: true });
for (const file of [
  "index.html",
  "app.js",
  "model.js",
  "styles.css",
  "tokens.css",
  "favicon.svg",
])
  await cp(file, `dist/${file}`);
await cp("public", "dist", { recursive: true });
await writeFile("dist/.nojekyll", "");
console.log(
  `Built dist/: ${data.players.length} players, ${data.events.length} events`,
);
