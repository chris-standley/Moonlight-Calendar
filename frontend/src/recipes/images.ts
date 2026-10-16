/** Shrink a photo before uploading: longest side `max` px, JPEG. Screens and phones take far bigger pictures than a
 *  recipe card needs, and the add-on keeps them in its database. */
export async function shrinkImage(file: Blob, max = 1600, quality = 0.85): Promise<Blob> {
  let bitmap: ImageBitmap;
  try { bitmap = await createImageBitmap(file); } catch { return file; } // unknown format: let the add-on say so
  const scale = Math.min(1, max / Math.max(bitmap.width, bitmap.height));
  const w = Math.round(bitmap.width * scale), h = Math.round(bitmap.height * scale);
  const canvas = document.createElement("canvas");
  canvas.width = w; canvas.height = h;
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, w, h);
  bitmap.close();
  return new Promise((res) => canvas.toBlob((b) => res(b ?? file), "image/jpeg", quality));
}
