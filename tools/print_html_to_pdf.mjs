/**
 * 用本机 Chrome/Edge 把 HTML 打印成带页码的 A4 PDF。
 * 复用 chainguard-web 已装的 playwright-core，不额外下载浏览器。
 *
 * 用法: node tools/print_html_to_pdf.mjs <input.html> <output.pdf> [页脚标题]
 */
import { createRequire } from "node:module";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WEB_DIR = path.join(HERE, "..", "chainguard-web");
const require = createRequire(path.join(WEB_DIR, "package.json"));

const CHROME_CANDIDATES = [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
];

async function main() {
  const [input, output, footerTitle = ""] = process.argv.slice(2);
  if (!input || !output) {
    console.error("用法: node tools/print_html_to_pdf.mjs <input.html> <output.pdf> [页脚标题]");
    process.exit(2);
  }

  const { chromium } = require("playwright-core");
  const launchOpts = {};
  if (!chromium.executablePath || !existsSync(chromium.executablePath())) {
    const found = CHROME_CANDIDATES.find((p) => existsSync(p));
    if (!found) {
      console.error("未找到可用的 Chrome/Edge，可执行 npx playwright install chromium");
      process.exit(3);
    }
    launchOpts.executablePath = found;
  }

  const browser = await chromium.launch(launchOpts);
  try {
    const page = await browser.newPage();
    await page.goto(pathToFileURL(path.resolve(input)).href, { waitUntil: "load" });
    await page.emulateMedia({ media: "print" });
    await page.pdf({
      path: path.resolve(output),
      format: "A4",
      printBackground: true,
      displayHeaderFooter: true,
      margin: { top: "20mm", right: "18mm", bottom: "18mm", left: "18mm" },
      headerTemplate: "<div></div>",
      footerTemplate: `<div style="width:100%;font-size:8pt;color:#7a7a7a;
          font-family:'Microsoft YaHei',sans-serif;padding:0 18mm;
          display:flex;justify-content:space-between;">
          <span>${footerTitle.replace(/[<>&]/g, "")}</span>
          <span>第 <span class="pageNumber"></span> 页 / 共 <span class="totalPages"></span> 页</span>
        </div>`,
    });
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
