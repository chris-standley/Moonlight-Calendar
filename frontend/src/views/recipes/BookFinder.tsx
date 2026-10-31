import { useEffect, useState } from "react";
import { ApiError, Cookbook } from "../../api/types";
import { useApp } from "../../state";
import { IconBarcode } from "../../components/icons";
import { canStream, hasCamera, readPhoto } from "../../recipes/barcode";
import { LiveScan } from "../../components/BarcodeScan";

/** "Which cookbook?" for a cookbook scan: the barcode on the back (camera, a photo of it, or a USB barcode reader
 *  typing into the ISBN box) finds the book's title, author and cover; or just type its name. */
export function BookFinder({ book, setBook, cookbook, setCookbook, disabled }: {
  book: string; setBook: (b: string) => void; cookbook: Cookbook | null; setCookbook: (c: Cookbook | null) => void; disabled?: boolean;
}) {
  const { api } = useApp();
  const [camera, setCamera] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [isbn, setIsbn] = useState("");
  const [finding, setFinding] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => { void hasCamera().then(setCamera); }, []);

  async function find(code: string) {
    if (!code.trim()) return;
    setFinding(true);
    setNote(null);
    try {
      const found = await api.findCookbook(code.trim());
      setCookbook(found);
      setBook(found.title);
    } catch (e) {
      setNote(e instanceof ApiError ? e.message : "Couldn't look that book up. Try again.");
    } finally { setFinding(false); }
  }
  async function photo(f: File | undefined) {
    if (!f) return;
    setNote(null);
    const code = await readPhoto(f).catch(() => null);
    if (code) { setIsbn(code); void find(code); } else setNote("Couldn't see a barcode in that photo. Get closer, keep it flat and in focus, or type the number under it.");
  }

  if (cookbook) return (
    <div className="book-found">
      {cookbook.cover_url ? <img src={cookbook.cover_url} alt="" /> : <span className="book-cover-blank">📚</span>}
      <div>
        <b>{cookbook.title}</b>
        <small className="muted">{[cookbook.authors, cookbook.year].filter(Boolean).join(" · ")}</small>
        <input className="input" value={book} onChange={(e) => setBook(e.target.value)} disabled={disabled} aria-label="Name kept with every recipe" placeholder="Name kept with every recipe" />
      </div>
      <button type="button" className="link" disabled={disabled} onClick={() => { setCookbook(null); setBook(""); setIsbn(""); }}>Not this book</button>
    </div>
  );

  return (
    <div className="book-finder">
      {scanning ? <LiveScan hint="Hold the barcode on the back inside the box" onCode={(c) => { setScanning(false); setIsbn(c); void find(c); }} onClose={() => setScanning(false)} />
        : camera && (canStream()
          ? <button type="button" className="btn ghost import-pick" disabled={disabled || finding} onClick={() => setScanning(true)}><IconBarcode size={22} /> Scan the book's barcode</button>
          : <label className={"btn ghost import-pick" + (disabled || finding ? " disabled" : "")}><IconBarcode size={22} /> Take a photo of the barcode
            <input type="file" accept="image/*" capture="environment" hidden disabled={disabled || finding} onChange={(e) => { void photo(e.target.files?.[0]); e.target.value = ""; }} />
          </label>)}
      <div className="book-isbn">
        <input className="input" inputMode="numeric" value={isbn} disabled={disabled} onChange={(e) => setIsbn(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void find(isbn); } }}
          placeholder={camera ? "Or type the ISBN" : "The ISBN under the barcode"} aria-label="ISBN" />
        <button type="button" className="btn ghost" disabled={disabled || finding || !isbn.trim()} onClick={() => void find(isbn)}>{finding ? "Finding…" : "Find"}</button>
      </div>
      {!camera && <small className="muted">A USB or Bluetooth barcode reader connected to this screen types the number in for you.</small>}
      <input className="input" value={book} onChange={(e) => setBook(e.target.value)} disabled={disabled} placeholder="Or just the book's name" aria-label="Which cookbook" />
      {note && <div className="connect-error" role="alert">{note}</div>}
    </div>
  );
}
