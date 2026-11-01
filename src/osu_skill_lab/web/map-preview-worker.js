import { parseOsu } from "./map-parser.js";
self.onmessage = async ({ data: { bytes, expectedSha } }) => {
  try {
    if (bytes.byteLength > 4 * 1024 * 1024)
      throw new Error("Файл больше 4 MiB");
    const hash = await crypto.subtle.digest("SHA-256", bytes);
    const sha = Array.from(new Uint8Array(hash), (v) =>
      v.toString(16).padStart(2, "0"),
    ).join("");
    if (sha !== expectedSha)
      throw new Error(
        "Это другая редакция карты. Выбери исходный .osu или добавь его как новую карту.",
      );
    const map = parseOsu(
      new TextDecoder("utf-8", { fatal: true }).decode(bytes),
    );
    self.postMessage({ map });
  } catch (error) {
    self.postMessage({ error: error.message || "Не удалось прочитать карту" });
  }
};
