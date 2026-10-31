import { useEffect, useRef, useState } from "react";
import { BarcodeKind, barcodeReader } from "../recipes/barcode";

/** The back camera, read a few times a second until a barcode of this kind is seen (a book's by default). */
export function LiveScan({ kind = "book", hint, onCode, onClose }: {
  kind?: BarcodeKind; hint: string; onCode: (code: string) => void; onClose: () => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let stream: MediaStream | null = null;
    let stopped = false;
    let timer = 0;
    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false });
        if (stopped) return;
        const v = video.current!;
        v.srcObject = stream;
        await v.play();
        const read = await barcodeReader(kind);
        const tick = async () => {
          if (stopped) return;
          const code = v.readyState >= 2 ? await read(v).catch(() => null) : null;
          if (stopped) return;
          if (code) { navigator.vibrate?.(60); onCode(code); return; }
          timer = window.setTimeout(tick, 200);
        };
        void tick();
      } catch (e) {
        setError(e instanceof DOMException && e.name === "NotAllowedError"
          ? "Moonlight isn't allowed to use the camera here. Allow it in the browser, or type the number under the barcode."
          : "Couldn't open the camera. Type the number under the barcode instead.");
      }
    })();
    return () => { stopped = true; clearTimeout(timer); stream?.getTracks().forEach((t) => t.stop()); };
  }, []);
  return (
    <div className="book-scan">
      {error ? <div className="connect-error" role="alert">{error}</div> : <>
        <div className="book-scan-view"><video ref={video} muted playsInline /><span className="book-scan-frame" aria-hidden /></div>
        <small>{hint}</small>
      </>}
      <button type="button" className="btn ghost" onClick={onClose}>{error ? "OK" : "Stop"}</button>
    </div>
  );
}
