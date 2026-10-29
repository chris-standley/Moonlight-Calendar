import { useEffect, useRef, useState } from "react";
import { IconCheck, IconClose } from "../../components/icons";

/** The back camera, full screen, for taking one cookbook page after another without leaving Moonlight. Each tap of
 *  the shutter keeps a picture here (nothing goes into the phone's photo library); Done hands them all back in order. */
export function PageCamera({ room, onDone, onClose }: {
  room: number; onDone: (pages: File[]) => void; onClose: () => void;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const [shots, setShots] = useState<{ file: File; url: string }[]>([]);
  const [ready, setReady] = useState(false);
  const [flash, setFlash] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const kept = useRef(shots);
  kept.current = shots;

  useEffect(() => {
    let stream: MediaStream | null = null;
    let stopped = false;
    (async () => {
      try {
        // As sharp as the camera allows: small print on a page needs it. 4:3 is what phone cameras take.
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 4096 }, height: { ideal: 3072 } }, audio: false });
        if (stopped) return;
        const v = video.current!;
        v.srcObject = stream;
        await v.play();
        setReady(true);
      } catch (e) {
        setError(e instanceof DOMException && e.name === "NotAllowedError"
          ? "Moonlight isn't allowed to use the camera here. Allow it in the browser, or choose photos instead."
          : "Couldn't open the camera. Choose photos instead.");
      }
    })();
    return () => { stopped = true; stream?.getTracks().forEach((t) => t.stop()); };
  }, []);
  // The thumbnails' memory goes when the camera closes; the pictures themselves carry on in the File objects.
  useEffect(() => () => kept.current.forEach((s) => URL.revokeObjectURL(s.url)), []);

  function shoot() {
    const v = video.current;
    if (!v || !ready || !v.videoWidth || shots.length >= room) return;
    const canvas = document.createElement("canvas");
    canvas.width = v.videoWidth;
    canvas.height = v.videoHeight;
    canvas.getContext("2d")!.drawImage(v, 0, 0);
    setFlash(true);
    setTimeout(() => setFlash(false), 120);
    navigator.vibrate?.(30);
    canvas.toBlob((b) => {
      if (!b) return;
      setShots((s) => {
        const file = new File([b], `page-${String(s.length + 1).padStart(3, "0")}.jpg`, { type: "image/jpeg" });
        return [...s, { file, url: URL.createObjectURL(file) }];
      });
    }, "image/jpeg", 0.92);
  }
  function remove(i: number) {
    setShots((s) => { URL.revokeObjectURL(s[i].url); return s.filter((_, j) => j !== i); });
  }

  const full = shots.length >= room;
  return (
    <div className="page-cam" role="dialog" aria-label="Take photos of the pages">
      <div className="page-cam-top">
        <button type="button" className="page-cam-round" onClick={onClose} aria-label="Cancel"><IconClose /></button>
        <b>{full ? "That's as many as one scan takes" : shots.length ? `${shots.length} page${shots.length === 1 ? "" : "s"}` : "Fill the screen with the page"}</b>
        <span className="page-cam-spacer" />
      </div>
      {error ? <div className="page-cam-error"><div className="connect-error" role="alert">{error}</div></div>
        : <video ref={video} muted playsInline onClick={shoot} />}
      {flash && <span className="page-cam-flash" aria-hidden />}
      {shots.length > 0 && (
        <div className="page-cam-strip">
          {shots.map((s, i) => (
            <span key={s.url} className="page-cam-thumb">
              <img src={s.url} alt={`Page ${i + 1}`} />
              <i>{i + 1}</i>
              <button type="button" onClick={() => remove(i)} aria-label={`Take out page ${i + 1}`}><IconClose size={14} /></button>
            </span>
          ))}
        </div>
      )}
      <div className="page-cam-bar">
        <span className="page-cam-spacer" />
        <button type="button" className="page-cam-shutter" disabled={!ready || full} onClick={shoot} aria-label="Take a photo of this page" />
        <span className="page-cam-spacer">
          <button type="button" className="btn" disabled={!shots.length} onClick={() => onDone(shots.map((s) => s.file))}><IconCheck size={20} /> Done</button>
        </span>
      </div>
    </div>
  );
}
