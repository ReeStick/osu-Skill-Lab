// Browser-only integration with a synthetic HTTP API; not a PostgreSQL test.
const { chromium } = require("playwright");
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const web = path.resolve(__dirname, "../../src/osu_skill_lab/web");
const fixture = fs.readFileSync(
  path.resolve(__dirname, "../fixtures/analytic-v14.osu"),
);
const sha = createHash("sha256").update(fixture).digest("hex");
const tags = [
  {
    id: "11111111-1111-4111-8111-111111111111",
    name: "Jumps",
    description: "Широкие переходы между объектами.",
  },
  {
    id: "22222222-2222-4222-8222-222222222222",
    name: "Streams",
    description: "Равномерные серии.",
  },
];
const rows = Array.from({ length: 61 }, (_, i) => ({
  analysis_id: i + 1,
  input_id: i + 1,
  sha256:
    i === 0
      ? sha
      : createHash("sha256")
          .update("map-" + i)
          .digest("hex"),
  beatmap_id: null,
  beatmap_set_id: i + 1,
  title: i === 60 ? "Beyond page one" : `Map ${i + 1}`,
  artist: "Synthetic fixture",
  version: "Insane",
  features: {
    hit_object_count: 8,
    circle_count: 5,
    slider_count: 2,
    red_bpm_min: 180,
    red_bpm_max: 180,
  },
}));
const labels = new Map(),
  writes = [];
let eventId = 0,
  failWrite = false,
  delayLabels = 0;
const readBody = (req) =>
  new Promise((resolve) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => resolve(Buffer.concat(chunks)));
  });
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost"),
    json = (data, status = 200) => {
      res.writeHead(status, { "Content-Type": "application/json" });
      res.end(JSON.stringify(data));
    };
  if (url.pathname === "/lab/api/collection") {
    const matches = rows.filter(
      (r) =>
        r.analysis_id > Number(url.searchParams.get("after_id") || 0) &&
        (r.title + r.artist + r.version)
          .toLowerCase()
          .includes((url.searchParams.get("q") || "").toLowerCase()),
    );
    const limit = Number(url.searchParams.get("limit") || 50);
    return json({
      rows: matches.slice(0, limit),
      next_cursor:
        matches.length > limit ? matches[limit - 1].analysis_id : null,
    });
  }
  if (url.pathname === "/lab/api/tags") {
    if (req.method === "POST") {
      const body = JSON.parse(await readBody(req));
      const tag = { id: "33333333-3333-4333-8333-333333333333", ...body };
      tags.push(tag);
      return json(tag, 201);
    }
    return json(tags);
  }
  const get = url.pathname.match(/^\/lab\/api\/analyses\/(\d+)\/labels$/);
  if (get) {
    const result = structuredClone(labels.get(Number(get[1])) || {});
    if (delayLabels) await new Promise((r) => setTimeout(r, delayLabels));
    return json(result);
  }
  const post = url.pathname.match(/^\/lab\/api\/tags\/([^/]+)\/labels$/);
  if (post) {
    const body = JSON.parse(await readBody(req));
    const mapLabels = labels.get(body.analysis_id) || {};
    const prior = mapLabels[post[1]];
    if (failWrite || (prior?.id ?? null) !== body.expected_event_id) {
      failWrite = false;
      return json({ detail: "Conflict" }, 409);
    }
    const event = {
      id: ++eventId,
      analysis_id: body.analysis_id,
      value: body.value,
      partition: body.partition,
      created_at: new Date().toISOString(),
    };
    mapLabels[post[1]] = event;
    labels.set(body.analysis_id, mapLabels);
    writes.push(body);
    return json(event, 201);
  }
  if (url.pathname === "/analyses" && req.method === "POST") {
    const bytes = await readBody(req);
    return json(
      {
        id: 1,
        beatmap: {
          input_id: 1,
          sha256: createHash("sha256").update(bytes).digest("hex"),
          title: "Imported map",
          artist: "Fixture",
          difficulty_name: "Insane",
        },
        features: rows[0].features,
      },
      201,
    );
  }
  const file =
    url.pathname === "/lab"
      ? "index.html"
      : url.pathname === "/lab/research"
        ? "research.html"
        : url.pathname.startsWith("/lab/assets/")
          ? url.pathname.slice("/lab/assets/".length)
          : "";
  if (!file || file.includes("..")) {
    res.writeHead(404);
    return res.end();
  }
  try {
    res.setHeader(
      "Content-Type",
      file.endsWith(".js")
        ? "text/javascript"
        : file.endsWith(".css")
          ? "text/css"
          : "text/html",
    );
    res.end(fs.readFileSync(path.join(web, file)));
  } catch {
    res.writeHead(404);
    res.end();
  }
});
(async () => {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.OSU_LAB_BROWSER_EXECUTABLE || undefined,
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  try {
    const page = await browser.newPage({
        viewport: { width: 1280, height: 1000 },
      }),
      errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/lab`);
    await page.waitForFunction(
      () =>
        document.querySelectorAll(".tag-button").length === 2 &&
        !document.querySelector(".tag-button").disabled,
    );
    assert.equal(await page.locator(".map-row").count(), 50);
    assert(await page.locator("#play").isDisabled());
    await page.locator(".tag-button").first().click();
    await page.waitForFunction(
      () =>
        document.querySelector(".tag-button").getAttribute("aria-pressed") ===
        "true",
    );
    assert.equal(writes.at(-1).value, "yes");
    await page.locator(".tag-button").first().click();
    await page.waitForFunction(
      () =>
        document.querySelector(".tag-button").getAttribute("aria-pressed") ===
        "false",
    );
    assert.equal(writes.at(-1).value, "unreviewed");
    await page.click("#undo");
    await page.waitForFunction(
      () =>
        document.querySelector(".tag-button").getAttribute("aria-pressed") ===
        "true",
    );
    await page.click("#review-mode");
    await page.click("#no");
    await page.waitForFunction(
      () => document.querySelector("#selected-title").textContent === "Map 2",
    );
    assert.equal(writes.at(-1).value, "no");
    await page.click("#undo");
    await page.waitForFunction(
      () =>
        document.querySelector("#selected-title").textContent === "Map 1" &&
        !document.querySelector("#yes").disabled,
    );
    assert.equal(writes.at(-1).value, "yes");
    const before = writes.length;
    await page.click("#next");
    await page.waitForFunction(() => !document.querySelector("#yes").disabled);
    assert.equal(writes.length, before);
    failWrite = true;
    await page.click("#yes");
    await page.waitForFunction(() => !document.querySelector("#yes").disabled);
    assert.equal(await page.locator("#selected-title").innerText(), "Map 2");
    assert.equal(writes.length, before);
    await page.click("#browse-mode");
    await page.locator(".map-row").first().click();
    await page.waitForFunction(
      () => !document.querySelector(".tag-button").disabled,
    );
    await page.locator("#preview-file").setInputFiles({
      name: "wrong.osu",
      mimeType: "text/plain",
      buffer: Buffer.from("wrong"),
    });
    await page.waitForFunction(() =>
      document
        .querySelector("#preview-status")
        .textContent.includes("другая редакция"),
    );
    assert(await page.locator("#play").isDisabled());
    await page.locator("#preview-file").setInputFiles({
      name: "fixture.osu",
      mimeType: "text/plain",
      buffer: fixture,
    });
    await page.waitForFunction(() => !document.querySelector("#play").disabled);
    assert(await page.locator("#preview-empty").isHidden());
    const initial = await page.locator("#seek").inputValue();
    await page.click("#play");
    await page.waitForFunction(
      (initial) =>
        Number(document.querySelector("#seek").value) > Number(initial) + 100,
      initial,
    );
    await page.click("#play");
    await page.locator("#seek").evaluate((el) => {
      el.value = 1000;
      el.dispatchEvent(new Event("input", { bubbles: true }));
    });
    assert.equal(await page.locator("#seek").inputValue(), "1000");
    await page.locator("#toast").evaluate((el) => (el.hidden = true));
    const art = process.env.OSU_LAB_SCREENSHOT_DIR;
    if (art) {
      fs.mkdirSync(art, { recursive: true });
      await page.screenshot({
        path: path.join(art, "workbench-light.png"),
        fullPage: true,
      });
    }
    await page.click("#theme");
    if (art)
      await page.screenshot({
        path: path.join(art, "workbench-dark.png"),
        fullPage: true,
      });
    for (const width of [768, 390, 320]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        ),
        false,
        `overflow at ${width}`,
      );
    }
    if (art)
      await page.screenshot({
        path: path.join(art, "workbench-mobile.png"),
        fullPage: true,
      });
    await page.setViewportSize({ width: 1280, height: 1000 });
    await page.click("#more");
    await page.waitForFunction(
      () => document.querySelectorAll(".map-row").length === 61,
    );
    await page.locator(".map-row").last().click();
    assert.equal(
      await page.locator("#selected-title").innerText(),
      "Beyond page one",
    );
    assert(await page.locator("#play").isDisabled());
    await page.fill("#search", "Beyond");
    await page.waitForFunction(
      () => document.querySelectorAll(".map-row").length === 1,
    );
    assert.equal(
      await page.locator("#selected-title").innerText(),
      "Beyond page one",
    );
    await page.fill("#search", "not present");
    await page.waitForFunction(() => !document.querySelector("#empty").hidden);
    assert(await page.locator("#next").isDisabled());
    await page.locator("#upload-files").setInputFiles({
      name: "upload.osu",
      mimeType: "text/plain",
      buffer: fixture,
    });
    await page.waitForFunction(
      () =>
        document.querySelector("#selected-title").textContent ===
          "Imported map" && !document.querySelector("#play").disabled,
    );
    await page.click("#new-tag");
    await page.fill("#tag-name", "Reading");
    await page.fill("#tag-definition", "Сложное чтение объектов.");
    await page.click("#create-tag");
    await page.waitForFunction(
      () => document.querySelectorAll(".tag-button").length === 3,
    );
    // Slow label responses for the previous map must not enable writes for that map.
    delayLabels = 150;
    await page.locator(".map-row").nth(1).click();
    await page.locator(".map-row").nth(2).click();
    await page.waitForFunction(
      () => !document.querySelector(".tag-button").disabled,
    );
    assert.equal(await page.locator("#selected-title").innerText(), "Map 3");
    delayLabels = 0;
    // Switching maps while a worker prepares geometry must clear the old preview.
    await page.locator("#preview-file").setInputFiles({
      name: "fixture.osu",
      mimeType: "text/plain",
      buffer: fixture,
    });
    await page.locator(".map-row").nth(3).click();
    await page.waitForTimeout(250);
    assert(await page.locator("#play").isDisabled());
    assert.deepEqual(errors, []);
    console.log(
      "PASS: catalog, paging/search, tagging/removal, review/skip, cross-map undo, conflict reconciliation, checksum mismatch, worker preview, play/seek, upload, tag creation, stale responses, themes, 1280/768/390/320 layouts. API is synthetic.",
    );
  } finally {
    await browser.close();
    server.close();
  }
})().catch((error) => {
  console.error(error);
  server.close();
  process.exitCode = 1;
});
