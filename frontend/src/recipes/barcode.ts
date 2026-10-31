// Reading a cookbook's or a shop product's barcode in the browser. The browser's own BarcodeDetector is used where
// there is one (Chrome on Android and Macs); everywhere else ZXing reads it, loaded only when a camera is opened.
// isbn13 is backend/moonlight/cookbooks.isbn13 and gtin is backend/moonlight/products.gtin in TypeScript: change both
// together.

/** The ISBN-13 for a barcode or typed ISBN (10 or 13 digits, dashes and spaces allowed), or null if the check digit
 *  is wrong. Book barcodes are EAN-13 numbers starting 978 or 979. */
export function isbn13(value: string): string | null {
  let s = (value || "").replace(/[\s-]/g, "").toUpperCase();
  const ean = (d: string) => [...d].reduce((n, ch, i) => n + Number(ch) * (i % 2 ? 3 : 1), 0);
  if (/^\d{9}[\dX]$/.test(s)) {
    if ([...s].reduce((n, ch, i) => n + (10 - i) * (ch === "X" ? 10 : Number(ch)), 0) % 11) return null;
    s = "978" + s.slice(0, 9);
    return s + String((10 - (ean(s) % 10)) % 10);
  }
  if (/^97[89]\d{10}$/.test(s)) return ean(s) % 10 ? null : s;
  return null;
}

/** The 13-digit code for a shop barcode or typed number (EAN-13, UPC-A's 12 or EAN-8's 8 digits, spaces allowed), or
 *  null when it isn't one or the check digit is wrong. */
export function gtin(value: string): string | null {
  let s = (value || "").replace(/[\s-]/g, "");
  if (!/^(\d{8}|\d{12,14})$/.test(s)) return null;
  if ([...s].reverse().reduce((n, ch, i) => n + Number(ch) * (i % 2 ? 3 : 1), 0) % 10) return null;
  if (s.length === 14) { if (!s.startsWith("0")) return null; s = s.slice(1); }
  return s.length === 12 ? "0" + s : s;
}

/** What a scan looks for: the ISBN on the back of a book, or any shop product's barcode. */
export type BarcodeKind = "book" | "shop";
const KINDS: Record<BarcodeKind, { formats: string[]; zxing: ("EAN_13" | "EAN_8" | "UPC_A")[]; code: (raw: string) => string | null }> = {
  book: { formats: ["ean_13"], zxing: ["EAN_13"], code: isbn13 },
  shop: { formats: ["ean_13", "ean_8", "upc_a"], zxing: ["EAN_13", "EAN_8", "UPC_A"], code: gtin },
};

/** Whether this device has a camera the page may use. Wall screens without one get the typed ISBN only. Live video
 *  needs a secure page (https, or the add-on in Home Assistant); elsewhere a photo of the barcode still works. */
export async function hasCamera(): Promise<boolean> {
  try {
    if (!navigator.mediaDevices?.enumerateDevices) return false;
    return (await navigator.mediaDevices.enumerateDevices()).some((d) => d.kind === "videoinput");
  } catch { return false; }
}

export const canStream = () => typeof window !== "undefined" && window.isSecureContext && !!navigator.mediaDevices?.getUserMedia;

type Source = HTMLVideoElement | HTMLImageElement | HTMLCanvasElement | ImageBitmap;
/** `sideways`: also look with the picture turned a quarter (for photos; video frames are read again soon anyway). */
type Reader = (src: Source, sideways?: boolean) => Promise<string | null>;

interface NativeDetector { detect(src: Source): Promise<{ rawValue: string }[]> }
declare const BarcodeDetector: {
  new (o: { formats: string[] }): NativeDetector; getSupportedFormats(): Promise<string[]>;
} | undefined;

const readers: Partial<Record<BarcodeKind, Promise<Reader>>> = {};

/** A function that finds a barcode in a picture or video frame and gives back its code (a book's ISBN-13, or a shop
 *  product's 13 or 8 digits), or null. */
export function barcodeReader(kind: BarcodeKind = "book"): Promise<Reader> {
  return (readers[kind] ??= makeReader(kind));
}

async function makeReader(kind: BarcodeKind): Promise<Reader> {
  const { formats, zxing, code: toCode } = KINDS[kind];
  try {
    if (typeof BarcodeDetector !== "undefined") {
      const have = await BarcodeDetector.getSupportedFormats();
      if (formats.every((f) => have.includes(f))) {
        const d = new BarcodeDetector({ formats });
        return async (src) => {
          for (const b of await d.detect(src)) { const code = toCode(b.rawValue); if (code) return code; }
          return null;
        };
      }
    }
  } catch { /* fall back to ZXing */ }
  const z = await import("@zxing/library");
  const hints = new Map<number, unknown>([[z.DecodeHintType.POSSIBLE_FORMATS, zxing.map((f) => z.BarcodeFormat[f])], [z.DecodeHintType.TRY_HARDER, true]]);
  const r = new z.MultiFormatReader();
  r.setHints(hints);
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
  return async (src, sideways) => {
    const w = src instanceof HTMLVideoElement ? src.videoWidth : src instanceof HTMLImageElement ? src.naturalWidth : src.width;
    const h = src instanceof HTMLVideoElement ? src.videoHeight : src instanceof HTMLImageElement ? src.naturalHeight : src.height;
    if (!w || !h) return null;
    const scale = Math.min(1, 1280 / Math.max(w, h));
    const [cw, ch] = [Math.round(w * scale), Math.round(h * scale)];
    // A photo of a barcode taken sideways reads too: the picture, then turned a quarter.
    for (const turn of sideways ? [false, true] : [false]) {
      [canvas.width, canvas.height] = turn ? [ch, cw] : [cw, ch];
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      if (turn) ctx.setTransform(0, 1, -1, 0, ch, 0);
      ctx.drawImage(src, 0, 0, cw, ch);
      const lum = new z.HTMLCanvasElementLuminanceSource(canvas);
      // The row-by-row binarizer copes better with a soft (slightly out of focus) picture, the local one with uneven light.
      for (const bin of [new z.GlobalHistogramBinarizer(lum), new z.HybridBinarizer(lum)]) {
        try {
          const code = toCode(r.decodeWithState(new z.BinaryBitmap(bin)).getText());
          if (code) return code;
        } catch { /* nothing found this way */ }
      }
    }
    return null;
  };
}

/** The code in a photo of the barcode, or null. */
export async function readPhoto(file: File, kind: BarcodeKind = "book"): Promise<string | null> {
  const read = await barcodeReader(kind);
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    return await read(img, true);
  } finally { URL.revokeObjectURL(url); }
}
