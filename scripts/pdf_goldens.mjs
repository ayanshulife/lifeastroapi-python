// Committed fixtures of the PDF template tests (tests/fixtures/pdf/*.json.gz).
//
// src/lifeastroapi/pdf must give byte-for-byte the HTML of the Node SDK's TypeScript
// templates (lifeastroapi-node/src/pdf). This renders the inputs below with those sources
// and stores inputs and expected HTML for tests/test_pdf_templates.py. It is the PHP SDK's
// tool/pdf-goldens.mjs, gzipped and in fewer files; the fixtures are not packaged.
//
// Inputs:
//   1. every render*Html call made by the Node SDK's own PDF tests (recorded while they
//      run against a stubbed `vitest`);
//   2. the real report responses in the website's examples.json, rendered in all 10
//      languages, with and without a branding override;
//   3. EDGE_CASES below: what real reports rarely hold and a port gets wrong easily.
//
// The full, untrimmed reports are checked by the deep test in tests/test_pdf_templates.py.
//
//   node scripts/pdf_goldens.mjs
//
// Environment: LIFEASTRO_NODE_SDK, LIFEASTRO_EXAMPLES (as scripts/generate.py).
// Needs the Node SDK's dev dependencies (esbuild): `npm install` in that repo.
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { gzipSync } from "node:zlib";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const NODE_SDK = resolve(process.env.LIFEASTRO_NODE_SDK ?? join(ROOT, "..", "lifeastroapi-node"));
const EXAMPLES = resolve(
  process.env.LIFEASTRO_EXAMPLES ??
    join(ROOT, "..", "LifeAstroAPI", "LifeAstroApiWebsite", "lib", "generated", "examples.json"),
);
const OUT = join(ROOT, "tests", "fixtures", "pdf");
const TMP = join(ROOT, "build", "pdf-goldens");

const require = createRequire(join(NODE_SDK, "package.json"));
const esbuild = require("esbuild");
const PDF_INDEX = join(NODE_SDK, "src", "pdf", "index.ts");

const RENDERERS = [
  "renderKundliLiteHtml",
  "renderKundliDetailedHtml",
  "renderKundliBrihadHtml",
  "renderMatchMakingHtml",
  "renderDashaAnalysisHtml",
  "renderNumerologyHtml",
  "renderSadeSatiHtml",
  "renderVarshaphalHtml",
  "renderHoroscopeHtml",
  "renderMangalDoshaHtml",
];

// A bundle that exposes the real templates plus a recorder around them.
const recorderSrc = `
import * as real from ${JSON.stringify(PDF_INDEX)};
export * from ${JSON.stringify(PDF_INDEX)};
globalThis.__pdfCalls = globalThis.__pdfCalls ?? [];
const rec = (name, fn) => (...args) => {
  globalThis.__pdfCalls.push({ fn: name, args: JSON.parse(JSON.stringify(args.map((a) => a ?? null))) });
  return fn(...args);
};
${RENDERERS.map((n) => `export const ${n} = rec(${JSON.stringify(n)}, real.${n});`).join("\n")}
`;

const stubVitest = `
const chain = new Proxy(function () {}, { get: () => chain, apply: () => chain });
const run = (fn) => { try { const r = fn?.(); if (r && typeof r.catch === "function") r.catch(() => {}); } catch {} };
export const describe = (_n, fn) => run(fn);
export const it = (_n, fn) => run(fn);
it.each = () => (_n, fn) => {};
export const test = it;
export const expect = () => chain;
export const vi = chain;
export const beforeAll = () => {}, afterAll = () => {}, beforeEach = () => {}, afterEach = () => {};
`;

const plugin = {
  name: "pdf-goldens",
  setup(build) {
    build.onResolve({ filter: /^vitest$/ }, () => ({ path: "vitest", namespace: "stub" }));
    build.onLoad({ filter: /.*/, namespace: "stub" }, () => ({ contents: stubVitest, loader: "js" }));
    build.onResolve({ filter: /src\/pdf\/index\.js$/ }, () => ({ path: "recorder", namespace: "rec" }));
    build.onLoad({ filter: /.*/, namespace: "rec" }, () => ({
      contents: recorderSrc,
      loader: "js",
      resolveDir: join(NODE_SDK, "src", "pdf"),
    }));
  },
};

rmSync(TMP, { recursive: true, force: true });
mkdirSync(TMP, { recursive: true });
// The Node tests' htmlToPdf cases reject without Puppeteer; only the render
// calls matter here.
process.on("unhandledRejection", () => {});

async function bundle(entry, outfile) {
  await esbuild.build({
    entryPoints: [entry],
    bundle: true,
    format: "esm",
    platform: "node",
    outfile,
    plugins: [plugin],
    logLevel: "error",
  });
  return import(pathToFileURL(outfile).href + `?t=${Date.now()}`);
}

// 1. Record the Node tests' calls.
for (const t of ["pdf.test.ts", "pdf-south-locales.test.ts"]) {
  await bundle(join(NODE_SDK, "test", t), join(TMP, t.replace(/\.ts$/, ".mjs")));
}
await new Promise((r) => setTimeout(r, 50)); // let async test bodies settle
const recorded = globalThis.__pdfCalls ?? [];

// The real templates (and the Brihad TOC helpers), bundled from the TS source.
const helpersEntry = join(TMP, "helpers.ts");
writeFileSync(
  helpersEntry,
  `export * from ${JSON.stringify(PDF_INDEX)};
export {
  brihadHeaderTemplate, brihadFooterTemplate, buildBrihadToc, tagBrihadSectionsForToc,
  brihadPalette, brihadPaletteCss, brihadWatermarkCss,
} from ${JSON.stringify(
    join(NODE_SDK, "src", "pdf", "templates", "kundliBrihadSections.ts"),
  )};
export { northIndianChartSvg, planetLabelsFor } from ${JSON.stringify(
    join(NODE_SDK, "src", "pdf", "templates", "northIndianChart.ts"),
  )};
export * as colors from ${JSON.stringify(join(NODE_SDK, "src", "pdf", "colors.ts"))};
export { layoutDocument } from ${JSON.stringify(join(NODE_SDK, "src", "pdf", "shared.ts"))};
export { printOptionsCss, mergeMargin } from ${JSON.stringify(join(NODE_SDK, "src", "pdf", "render.ts"))};
export { TOC_HEADING } from ${JSON.stringify(join(NODE_SDK, "src", "pdf", "locales.ts"))};
`,
);
const pdf = await bundle(helpersEntry, join(TMP, "helpers.mjs"));

// 2. Real report responses in every locale.
// Port traps: un-padded years and Date limits, JS truthiness, JS \s, emoji next to a dash, PART banners.
const EDGE_CASES = [
  ["renderKundliLiteHtml", { Locale: "pa", GeneratedAt: "0001-01-01T00:00:00Z", Subject: { Name: "Arjun Mehta" } }],
  ["renderKundliLiteHtml", { GeneratedAt: "2026-02-30" }],
  ["renderKundliLiteHtml", { GeneratedAt: "2026-11-22T23:59:60Z" }],
  ["renderKundliLiteHtml", { GeneratedAt: "2026-11-22T11:12:01.123456789+05:30" }],
  ["renderKundliLiteHtml", { LagnaSummary: "a\ufeff,b c\u0085,d 😀–😀–e", Ascendant: { pada: 1e21 } }],
  ["renderKundliLiteHtml", { Subject: { Name: "x" } }, { primaryColor: "rgb(1,\ufeff2,3)", secondaryColor: "rgb(1,\u00852,3)", companyName: "\u0085", footerText: "\ufeff" }],
  ["renderDashaAnalysisHtml", { Locale: "pa", ActivePath: false }],
  ["renderDashaAnalysisHtml", { Locale: "pa", ActivePath: { Maha: "", MahaBody: "ਫਲ" }, YoginiDashas: [{ Lord: "Mangala", DurationY: 1.0 }] }],
  ["renderSadeSatiHtml", { Locale: "pa", CurrentStatus: { status: "peak", moon_sign: "ਕਰਕ", saturn_sign: "ਮੀਨ" }, Past: [{ DurationYears: 7.25, SignsTraversed: ["ਕਰਕ"] }] }],
  ["renderVarshaphalHtml", { Locale: "pa", TargetYear: 2027, Muntha: { house: 8 } }],
  ["renderVarshaphalHtml", { SolarReturnISO: "2027-01-15T16:39:17Z", SolarReturnLocal: "2027-01-15 22:09 IST" }],
  ["renderVarshaphalHtml", { SolarReturnISO: "2027-01-15T16:39:17.5+05:30" }],
  ["renderNumerologyHtml", { name: "Arjun Mehta", driver: 6, Subject: { Name: "" } }],
  ["renderKundliBrihadHtml", { Ascendant: { sign: "Aries" }, rajyoga_power: { percent: 5, planets: ["<b>Sun", "Moon"] },
    kp: { cusps: [{ house: 1 }], planet_significators: [{ key: "Sun", values: ["<i>2", 11] }] },
    Planets: [["Sun", 3], ["Moon", 3], ["Mars", 3], ["Mercury", 11], ["Venus", 1], ["Saturn", 1]].map(([name, house_num]) => ({ name, house_num })) }],
  ["renderKundliLiteHtml", { GeneratedAt: "2026-11-22T23:30" }],
  ["renderKundliLiteHtml", { GeneratedAt: "2026-11-22 23:30:15.5" }],
  ["renderKundliLiteHtml", { GeneratedAt: "2026-11-22t23:30" }],
  ["renderKundliBrihadHtml", { Locale: "mr", Ascendant: { sign: "मेष" }, DivisionalCharts: [{ varga: "D2", lagna_sign: "तूळ",
    planets: ["सूर्य", "चंद्र", "मंगळ", "बुध", "बृहस्पती", "शुक्र", "शनी", "राहू", "केतू"].map((name, i) => ({ name, house: (i % 2) + 1 })) }],
    Planets: ["मंगळ", "बृहस्पती", "शनी", "राहू", "केतू"].map((name, i) => ({ name, house_num: i + 1 })) }],
  ["renderKundliBrihadHtml", { GeneratedAt: "2026-11-22T23:30:15.123456789", Locale: "toString" }],
  ["renderMangalDoshaHtml", { Locale: "constructor", HasDosha: true, Status: "mild", HousesOccupied: [7, -4] }],
  ["renderHoroscopeHtml", { language: "__proto__", rashi: "Mesha" }],
  // Brand palette, watermark, API codes, short sections, the Mangal row.
  ["renderKundliBrihadHtml", {
    Branding: { PrimaryColor: "#1A1A1A", SecondaryColor: " #666666 " }, Ascendant: { sign: "Leo" },
    Planets: [{ name: "Sun", house_num: 1 }], ishta_devata: { deity: "Vishnu" },
    maitri: { order: ["Sun", "Moon", "constructor"], tatkalik: [{ planet: "Sun", relations: { Sun: "TempFriend", Moon: "TempEnemy" } }] },
    Remedies: [{ Title: "A", Category: "graha_shanti" }, { Title: "B", Category: "charity" }, { Title: "C", Category: "Graha_x" }],
    rajyoga_power: { percent: 5, swarnim_kaal: [{ lord: "Moon" }, { lord: "Sun" }] },
  }, { watermarkText: "DRAFT FOR REVIEW ONLY" }],
  ["renderKundliBrihadHtml", { Ascendant: { sign: "Aries" }, rajyoga_power: { swarnim_kaal: [{}, {}, {}] } },
    { primaryColor: "#ffe14d", secondaryColor: "hsl(150, 80%, 30%)", watermarkText: "CONFIDENTIAL", companyName: "Acme — Astro" }],
  ["renderKundliBrihadHtml", { Branding: { PrimaryColor: "rgb(11 92 173)" } }, { secondaryColor: "\u00a0" }],
  ["renderMangalDoshaHtml", { Locale: "pa", HasDosha: false, Status: "none", HousesOccupied: null }],
  ["renderKundliLiteHtml", {}, { primaryColor: "Yellow", secondaryColor: "#05af", logoUrl: "//cdn.example/l.png", footerText: "© Acme — <private>" }],
  ["renderKundliLiteHtml", {}, { logoUrl: "https://cdn.example/a,,b->c.png?x=1&y=2", secondaryColor: "rgb(1 2 3 / 50%)", watermarkText: "A/*B*/C" }],
  // A field that should be a list and is not, or is a list with a null inside.
  ...["1, 5", { a: 1 }, 7, 2.5, true, "", null, [null], ["x", null], [7, null], [null, {}], [[null]]].flatMap((v) => [
    ["renderKundliBrihadHtml", { narrative_chapters: v, gems: { stones: v },
      DivisionalCharts: [{ varga: "D9", lagna_sign: "Leo", planets: v }],
      chalit: { houses: [{ house: 1 }], planets: v },
      kp: { cusps: [{ house: 1 }], planet_significators: [{ key: "Sun", values: v }] },
      jaimini: { charakarakas: v, arudha_padas: [{ label: "AL", sign: "Leo" }] }, lal_kitab: { planets: v, rins: [{ name: "Pitri" }] },
      ashtakavarga: { sav: [28], prastar: v }, varshaphal: [{ year: 2027, sahams: v, panchavargeeya: v }],
      mudda_timeline: { periods: [{ areas: v }] }, rajyoga_power: { percent: 5, planets: v, swarnim_kaal: v } }],
    ["renderKundliBrihadHtml", { kp: { cusps: [{ house: 1 }], planet_significators: v } }],
    ["renderMatchMakingHtml", { Locale: "hi", MangalDoshaBoy: { Computed: true, HasDosha: true, HousesOccupied: v } }],
    ["renderMatchMakingHtml", { Locale: "ta", MangalDoshaGirl: { Computed: true, HasDosha: true, HousesOccupied: v } }],
    ["renderSadeSatiHtml", { Past: [{ SignsTraversed: v }], Current: { SignsTraversed: v } }],
  ]),
  ["renderKundliBrihadHtml", { Planets: [null] }],
  ["renderKundliBrihadHtml", { Planets: ["x", null] }],
  ["renderKundliBrihadHtml", { Planets: [7, null] }],
  ["renderKundliBrihadHtml", { narrative_chapters: [{ key: "outlook" }, null] }],
  ["renderKundliBrihadHtml", { ashtakavarga: { sav: [28, null, 30] }, Planets: [null, { name: "Sun", house_num: 1 }, null] }],
  ["renderKundliDetailedHtml", { Planets: [{}, null] }],
  ["renderDashaAnalysisHtml", { AllMahadashas: [null] }],
  ["renderHoroscopeHtml", { slow_movers: [null] }],
];
const LOCALES = ["en", "hi", "mr", "te", "ta", "kn", "ml", "gu", "bn", "pa"];
const BRANDING = {
  companyName: "Acme Astro",
  logoUrl: "https://cdn.example/acme/logo.png",
  primaryColor: "#6b21a8",
  secondaryColor: "#9333ea",
  footerText: "Acme Astro · confidential",
  watermarkText: "SAMPLE",
};
const REPORTS = {
  "/v1/reports/kundli/lite": "renderKundliLiteHtml",
  "/v1/reports/kundli/detailed": "renderKundliDetailedHtml",
  "/v1/reports/kundli/brihad": "renderKundliBrihadHtml",
  "/v1/reports/match-making": "renderMatchMakingHtml",
  "/v1/reports/dasha-analysis": "renderDashaAnalysisHtml",
  "/v1/reports/numerology": "renderNumerologyHtml",
  "/v1/reports/sade-sati": "renderSadeSatiHtml",
  "/v1/reports/varshaphal": "renderVarshaphalHtml",
  "/v1/reports/mangal-dosha": "renderMangalDoshaHtml",
};
const cases = [];
const seen = new Set();
function addCase(fn, args) {
  const key = fn + JSON.stringify(args);
  if (seen.has(key)) return;
  seen.add(key);
  cases.push({ fn, args });
}
for (const c of recorded) addCase(c.fn, c.args.length === 1 ? [c.args[0], null] : c.args);
// Horoscope reports have no example response (the examples run without a
// live corpus); render the Node test inputs in every locale instead.
for (const c of recorded.filter((r) => r.fn === "renderHoroscopeHtml")) {
  for (const loc of ["en", "hi", "mr", "te", "ta", "kn", "ml", "gu", "bn", "pa"]) {
    addCase(c.fn, [{ ...c.args[0], language: loc }, c.args[1] ?? null]);
  }
}
if (existsSync(EXAMPLES)) {
  const ex = JSON.parse(readFileSync(EXAMPLES, "utf8"));
  for (const [path, fn] of Object.entries(REPORTS)) {
    const resp = ex[path]?.response;
    if (!resp || typeof resp !== "object") continue;
    for (const loc of LOCALES) addCase(fn, [{ ...resp, Locale: loc }, null]);
    addCase(fn, [resp, BRANDING]);
    addCase(fn, [{ ...resp, Locale: "hi" }, BRANDING]);
  }
} else {
  throw new Error(`examples.json not found at ${EXAMPLES}: set LIFEASTRO_EXAMPLES`);
}
for (const [fn, data, branding] of EDGE_CASES) addCase(fn, [data, branding ?? null]);

// Render.
// The first case of each report keeps its whole HTML, so a failure shows where it differs;
// the others keep the SHA-256, which is as strict and keeps the fixtures small.
mkdirSync(OUT, { recursive: true });
const save = (name, value) => writeFileSync(join(OUT, `${name}.json.gz`), gzipSync(JSON.stringify(value), { level: 9 }));
const sha256 = (text) => createHash("sha256").update(text).digest("hex");
const rendered = new Map();
const counters = {};
const index = [];
for (const c of cases) {
  const short = c.fn.replace(/^render/, "").replace(/Html$/, "");
  const name = short[0].toLowerCase() + short.slice(1);
  counters[name] = (counters[name] ?? 0) + 1;
  const id = `${name}-${String(counters[name]).padStart(3, "0")}`;
  const args = JSON.parse(JSON.stringify(c.args));
  const html = pdf[c.fn](args[0], args[1] ?? undefined);
  rendered.set(id, html);
  const expected = { sha256: sha256(html), ...(counters[name] === 1 ? { html } : {}) };
  index.push({ id, fn: c.fn, data: c.args[0], branding: c.args[1], ...expected });
}
save("cases", index);

// Text helpers: every string in the inputs, through humanize / cleanNarrative / esc.
const strings = new Set();
const walk = (v) => {
  if (typeof v === "string") strings.add(v);
  else if (Array.isArray(v)) v.forEach(walk);
  else if (v && typeof v === "object") Object.values(v).forEach(walk);
};
for (const c of cases) walk(c.args);
for (const s of [
  "A — B", "x – y", "a -> b => c", "—", " – ", "word —", "— word", "a , , b", "(, x ,)",
  "In Vedic astrology the chart is read on three levels: birth, dasha and transit. It is about guidance.",
  "the native's career; The native is calm; native's luck; native",
  "जातक की कुंडली में जातक को लाभ। जातक",
  "जातकाच्या जीवनात जातकाला यश जातक",
  "ਤੁਸੀਂ ਮਿਹਨਤ — ਧੀਰਜ ਨਾਲ ਫਲ ਪਾਉਂਦੇ ਹੋ; native", "😀–😀–e", "x\u0085", "\ufeffx , y\u180e",
  "फल। यह कुंडली जीवन के तीन स्तरों पर है और यह शास्त्र है। अंत",
  "फल। जन्म और गोचर, इन तीन स्तरों पर देख कर कहिए। अंत",
  // JavaScript's white space, ASCII word boundaries and arrows that follow each other.
  "a \u2192 \u2192 b", "a \r\n b", "nativ\u00e9 native\u0939", "x  ,  )", "line  \t\n\n\n\nnext", "$& $1 \\1 <&>",
]) strings.add(s);
const text = [];
for (const s of [...strings].sort()) {
  const row = { s, humanize: pdf.humanize(s), esc: pdf.esc(s), clean: {} };
  for (const loc of ["en", "hi", "mr", "te", "gu", "pa"]) row.clean[loc] = pdf.cleanNarrative(s, loc);
  text.push(row);
}
save("text", text);

// Brihad running header/footer, TOC, section tagging, print geometry and the outline writer.
const TOC_ENTRIES = [
  { title: "Part 1: Birth Details", page: 3 },
  { title: "Planets & <Houses>", page: 7 },
  { title: "भाग 2: दशा", page: 12 },
  { title: "ਭਾਗ 3: ਯੋਗ ਅਤੇ ਦੋਸ਼", page: 20 },
];
// A 3-page xref-table PDF, as in the Node SDK's outline test.
// `information` adds a Title and bytes that are not windows-1252 text, as Chromium writes them.
function minimalPdf(information = false) {
  const objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R 4 0 R 5 0 R] /Count 3 >>"];
  for (let i = 0; i < 3; i++) objs.push("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>");
  if (information) objs.push("<< /Title (Report) >>");
  let body = information ? "%PDF-1.4\n%\u0080\u0081\u0099\u009f\n" : "%PDF-1.4\n";
  let xref = "0000000000 65535 f \n";
  objs.forEach((o, i) => {
    xref += `${String(body.length).padStart(10, "0")} 00000 n \n`;
    body += `${i + 1} 0 obj\n${o}\nendobj\n`;
  });
  const at = body.length;
  const size = objs.length + 1;
  const info = information ? " /Info 6 0 R" : "";
  body += `xref\n0 ${size}\n${xref}trailer\n<< /Size ${size} /Root 1 0 R${info} >>\nstartxref\n${at}\n%%EOF\n`;
  return Buffer.from(body, "latin1");
}
const outlineItems = [
  { title: "ਭਾਗ 1: ਆਧਾਰ", page: 1, level: 1 },
  { title: "Planets (D1) \\ 😀", page: 2, level: 2 },
  { title: "ജനന വിവരം", page: 99, level: 2 },
  { title: "ഭാഗം 2: ലഗ്നം (D1) ਊ", page: 2, level: 1 },
  { title: " ", page: 2, level: 1 },
  { title: "பகுதி 2", page: 3, level: 1 },
];
const brihad = {
  a4: pdf.A4_PRINT_OPTIONS,
  outlines: [false, true].map((information) => ({
    pdf: minimalPdf(information).toString("base64"),
    items: outlineItems,
    result: Buffer.from(pdf.addPdfOutline(new Uint8Array(minimalPdf(information)), outlineItems)).toString("base64"),
  })),
  header: [pdf.brihadHeaderTemplate(undefined), pdf.brihadHeaderTemplate({ ...BRANDING })],
  footer: [pdf.brihadFooterTemplate(undefined), pdf.brihadFooterTemplate({ ...BRANDING })],
  toc: LOCALES.filter((l) => pdf.TOC_HEADING[l]).map((l) => ({
    heading: pdf.TOC_HEADING[l],
    entries: TOC_ENTRIES,
    html: pdf.buildBrihadToc(TOC_ENTRIES, pdf.TOC_HEADING[l]),
  })),
  tagged: index
    .filter((c) => c.fn === "renderKundliBrihadHtml")
    .map((c) => {
      const { html, titles } = pdf.tagBrihadSectionsForToc(rendered.get(c.id));
      return { id: c.id, titles, sha256: sha256(html) };
    }),
};
save("brihad", brihad);

// Colours, palette, watermark sizes and print options (src/pdf/colors.ts, render.ts).
const API_DEFAULTS = { PrimaryColor: "#1a1a1a", SecondaryColor: "#666666", FooterText: "Generated using LifeAstroAPI" };
const COLOURS = [
  "#0B5CAD", "#05a", "#05af", "#0000", "#0b5cadff", "#0b5cad80", "#12345", "RebeccaPurple", "INDIGO", "\u0130NDIGO",
  "\u212ahaki", "tan", "white", "yellow", "constructor", "toString", "inherit", "transparent", "", "  ",
  " #666666 ", "\u00a0#666666\ufeff", "\u0085#666666", "#666666\n", "#\u0661\u0661\u0661",
  "rgb(11, 92, 173)", "rgb(11 92 173)", "rgb(11\u00a092\u00a0173)", "rgb(11\u008592\u0085173)", "rgb(0.5, 1.5, 2.5)",
  "rgb(100%, 0%, 0%)", "rgba(0,0,0,0.5)", "rgba(0,0,0,.1)", "rgba(0,0,0,0)", "rgb(1 2 3 / 50%)", "rgb(300, 1, 2)",
  "rgb(1,2)", "rgb(1., 2, 3)", "rgb(1.2.3, 4, 5)", "RGB(1,2,3)", "hsl(210, 100%, 50%)", "hsla(400.5 33.3% 70% / .7)",
  "hsl(1,2,3)", "hsl(10%, 20%, 30%)", `#${"0".repeat(70)}`, `rgb(${" ".repeat(50)}1, 2, 3)`, `rgb(${" ".repeat(55)}1, 2, 3)`,
];
for (let r = 0; r < 256; r += 51) for (let g = 0; g < 256; g += 51) for (let b = 0; b < 256; b += 51) {
  COLOURS.push(pdf.colors.toHex([r, g, b]));
}
const colours = COLOURS.map((value) => {
  const rgb = pdf.colors.parseColor(value);
  const c = pdf.colors;
  return { value, rgb: rgb ?? null, printable: c.printableColor(value, "#1a1a1a"),
    ...(rgb ? { dark: c.toHex(c.darkenToContrast(rgb, 5.2)), tint: c.toHex(c.tintOnWhite(rgb, 5)), fill: c.seeThrough(rgb) } : {}) };
});
const REPORT_BRANDS = [null, {}, API_DEFAULTS, { ...API_DEFAULTS, PrimaryColor: "#1A1A1A", SecondaryColor: " #666666 " },
  { ...API_DEFAULTS, PrimaryColor: "#0b5cad" }, { SecondaryColor: "#0b6b36", CompanyName: "Json — Co" }];
const CALLER_BRANDS = [null, {}, { primaryColor: "#0b5cad", secondaryColor: "#0b6b36" }, { primaryColor: "#1a1a1a" },
  { primaryColor: "#1a1a1a", secondaryColor: "#666666" }, { secondaryColor: "#666666" }, { primaryColor: "notacolour" },
  { primaryColor: " ", secondaryColor: "\u00a0", companyName: "\ufeff", footerText: " " },
  { primaryColor: "yellow", watermarkText: "SAMPLE", companyName: "Acme — A&B", footerText: "© Acme — <private>" }];
const palettes = REPORT_BRANDS.flatMap((report) => CALLER_BRANDS.map((caller) => {
  const args = [report ?? undefined, caller ?? undefined];
  const palette = pdf.brihadPalette(...args);
  const resolved = pdf.resolveBranding(...args);
  return { report, caller, palette: palette ? JSON.parse(JSON.stringify(palette)) : null,
    css: pdf.brihadPaletteCss(palette) + pdf.brihadWatermarkCss(resolved, palette),
    header: pdf.brihadHeaderTemplate(...args), footer: pdf.brihadFooterTemplate(...args) };
}));
const watermarks = ["SAMPLE", "CONFIDENTIAL", "DRAFT FOR REVIEW ONLY", "x".repeat(500), "x".repeat(8), "x y".repeat(7),
  "\ud83d\ude00".repeat(9), "\u0a28\u0a2e\u0a42\u0a28\u0a3e", "e\u0301".repeat(6), " \u00a0A\ufeff", "A\u00a0B\u2028C", "A\u0085B\u0085C".repeat(9),
].map((text) => {
  const html = pdf.layoutDocument({ title: "t", branding: pdf.resolveBranding(undefined, { watermarkText: text }), bodyHtml: "" });
  return { text, size: Number(/body::before \{[^}]*font-size: (\d+)pt/.exec(html)[1]) };
});
const MARGINS = [null, {}, { top: "40mm", left: "0" }, { top: "12" }, { top: " ", right: "\ufeff" }, { bottom: "1.5CM", right: ".5in" },
  { top: "10 mm" }, { top: "-3mm" }, { left: 0, right: 12.5 }, { top: "\u00a07px" }];
const print = [];
for (const margin of MARGINS) {
  for (const format of ["A3", "A4", "A5", "Letter", "Legal", "Tabloid"]) {
    for (const landscape of [false, true]) {
      for (const preferCSSPageSize of [null, true, false]) {
        const options = { format, landscape, preferCSSPageSize, margin };
        const given = { format, landscape, preferCSSPageSize: preferCSSPageSize ?? undefined, margin: margin ?? undefined };
        print.push({ options, css: pdf.printOptionsCss(given) });
      }
    }
  }
}
for (const displayHeaderFooter of [null, false, true]) {
  for (const footerTemplate of [null, "", "<b>x</b>"]) {
    for (const printBackground of [true, false]) {
      for (const margin of [null, { top: "1cm" }]) {
        const options = { displayHeaderFooter, footerTemplate, printBackground, margin };
        const given = { displayHeaderFooter: displayHeaderFooter ?? undefined, footerTemplate: footerTemplate ?? undefined,
          printBackground, margin: margin ?? undefined };
        print.push({ options, css: pdf.printOptionsCss(given) });
      }
    }
  }
}
const BRIHAD_MARGIN = { top: "26mm", bottom: "16mm", left: "0mm", right: "0mm" };
const merged = MARGINS.map((margin) => ({ margin, merged: pdf.mergeMargin(BRIHAD_MARGIN, margin ?? undefined) }));
save("options", { colours, palettes, watermarks, print, merged });

// The chart's layout: every house with 1 to 14 bodies (more than any layout holds), and a full chart.
const BODIES = Object.keys(pdf.planetLabelsFor("en"));
const body = (i, house) => {
  const name = BODIES[i % BODIES.length];
  return { house, label: pdf.planetLabelsFor("ml")[name], ...(i % 2 ? { color: "#123456" } : {}) };
};
const charts = [{ lagnaSignIndex: 0, planets: Array.from({ length: 24 }, (_, i) => body(i, (i * 5) % 12 + 1)) }];
for (let house = 1; house <= 12; house++) {
  for (let count = 1; count <= 14; count++) {
    charts.push({ lagnaSignIndex: house + count, planets: Array.from({ length: count }, (_, i) => body(i, house)) });
  }
}
save("charts", charts.map((opts) => ({ opts, sha256: sha256(pdf.northIndianChartSvg(opts)) })));

// JavaScript number formatting and rounding, for tests/test_pdf_js.py.
const numbers = [
  0, -0, 1, -1, 0.5, 2.5, -2.5, 0.125, 0.375, 0.045, 1.005, 2.675, -0.001, 1e-7, 1.5e-7, 1e-6, 1.25e-5, 100,
  0.1 + 0.2, 1 / 3, 99.995, 123456789.125, 1e20, 123e18, 1e21, 1.7976931348623157e308, 5e-324, 2 ** 53 + 2,
  -0.5, 0.49999999999999994, 1.45, 2.35, 8.55, 16.1, -3.25, 4503599627370495.5,
];
save("numbers", numbers.map((n) => ({ n, text: String(n), fixed: [n.toFixed(0), n.toFixed(1), n.toFixed(2)],
  rounded: [String(Math.round(n)), String(Math.round(n * 10) / 10)] })));
rmSync(TMP, { recursive: true, force: true });

const byFn = {};
for (const c of index) byFn[c.fn] = (byFn[c.fn] ?? 0) + 1;
console.log(`${index.length} golden HTML files (${recorded.length} calls recorded from the Node tests).`);
console.log(byFn);
console.log(`${text.length} text-helper rows.`);
