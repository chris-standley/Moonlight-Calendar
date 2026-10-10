import { useRef, useState } from "react";
import { ApiError, Photo } from "../api/types";
import { useApp, useData } from "../state";
import { Empty, Sheet } from "../components/ui";
import { IconPhotos, IconPlus, IconTrash } from "../components/icons";

const MAX_MB = 25;

function fmtDay(isoTime: string | null): string {
  if (!isoTime) return "";
  return new Date(isoTime).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
}

/** Photo albums for the screensaver: browse, upload (works from the phone layout), delete with PIN. */
export function PhotosView({ onSlideshow }: { onSlideshow: (album: string | null) => void }) {
  const { api, askPin, toast } = useApp();
  const [albumId, setAlbumId] = useState<string | null>(null); // null = all photos
  const [albums] = useData((a) => a.albums(), ["photos"], []);
  const [photos] = useData((a) => a.photos(albumId), ["photos"], [albumId]);
  const [open, setOpen] = useState<Photo | null>(null);
  const [newAlbum, setNewAlbum] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const album = albums?.find((a) => a.id === albumId);
  const total = albums?.reduce((n, a) => n + a.photo_count, 0) ?? 0;

  async function upload(list: FileList | null) {
    const files = Array.from(list ?? []);
    if (input.current) input.current.value = "";
    if (!files.length) return;
    const target = albumId ?? albums?.[0]?.id ?? null;
    const errors: string[] = [];
    let added = 0;
    setProgress({ done: 0, total: files.length });
    // One request per photo: steady progress, and one bad file never sinks the rest.
    for (const [i, f] of files.entries()) {
      if (f.size > MAX_MB * 1024 * 1024) errors.push(`${f.name} is larger than ${MAX_MB} MB`);
      else {
        try {
          const r = await api.uploadPhotos(target, [f]);
          added += r.uploaded.length;
          errors.push(...r.errors.map((e) => e.detail));
        } catch (e) { errors.push(e instanceof ApiError ? e.message : `${f.name}: upload failed`); }
      }
      setProgress({ done: i + 1, total: files.length });
    }
    setProgress(null);
    if (added) toast(`Added ${added} photo${added === 1 ? "" : "s"}`);
    errors.slice(0, 3).forEach((e) => toast(e));
  }

  async function remove(p: Photo) {
    const pin = await askPin("Delete this photo");
    if (!pin) return;
    try { await api.deletePhoto(p.id, pin); setOpen(null); toast("Photo deleted"); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't delete"); }
  }

  async function removeAlbum() {
    if (!album) return;
    const pin = await askPin(`Delete the album "${album.name}" and its ${album.photo_count} photos`);
    if (!pin) return;
    try { await api.deleteAlbum(album.id, pin); setAlbumId(null); toast("Album deleted"); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't delete"); }
  }

  const count = albumId ? album?.photo_count ?? 0 : total;
  return (
    <div className="photos-view">
      <div className="toolbar">
        <div className="toolbar-l">
          <h1 className="toolbar-title">Photos<span className="sub">{count} photo{count === 1 ? "" : "s"}</span></h1>
        </div>
        <div className="toolbar-r">
          <button className="btn ghost" onClick={() => onSlideshow(albumId)}>
            <IconPhotos size={20} /> Start slideshow
          </button>
          <label className={"btn" + (progress ? " busy" : "")}>
            <IconPlus size={20} /> Upload
            <input ref={input} type="file" accept="image/*" multiple hidden disabled={!!progress}
              onChange={(e) => upload(e.target.files)} />
          </label>
        </div>
      </div>
      <div className="album-tabs">
        <button className={"chip-btn" + (albumId === null ? " on" : "")} onClick={() => setAlbumId(null)}>All <span>{total}</span></button>
        {(albums ?? []).map((a) => (
          <button key={a.id} className={"chip-btn" + (albumId === a.id ? " on" : "")} onClick={() => setAlbumId(a.id)}>
            {a.name} <span>{a.photo_count}</span>
          </button>
        ))}
        <button className="chip-btn add" onClick={() => setNewAlbum(true)}><IconPlus size={16} /> Album</button>
        {album && (albums?.length ?? 0) > 1 && (
          <button className="chip-btn danger" onClick={removeAlbum}><IconTrash size={16} /> Delete album</button>
        )}
      </div>
      {progress && (
        <div className="upload-bar">
          <span>Uploading {Math.min(progress.done + 1, progress.total)} of {progress.total}…</span>
          <i style={{ width: `${(progress.done / progress.total) * 100}%` }} />
        </div>
      )}
      <div className="photo-grid-wrap">
        {photos && photos.length === 0 ? (
          <Empty>
            No photos yet. Tap <b>Upload</b> to add some; from an iPhone, open Moonlight in the Home Assistant app and
            upload straight from your camera roll. Until then the screensaver shows painted landscapes.
          </Empty>
        ) : (
          <div className="photo-grid">
            {(photos ?? []).map((p) => (
              <button key={p.id} className="photo-tile" onClick={() => setOpen(p)} aria-label={p.filename}>
                <img src={p.thumb_url} alt="" loading="lazy" decoding="async" />
              </button>
            ))}
          </div>
        )}
      </div>
      {open && (
        <Sheet wide title={open.filename} onClose={() => setOpen(null)} footer={<>
          <button className="btn ghost danger" onClick={() => remove(open)}><IconTrash size={18} /> Delete</button>
          <span className="photo-meta">
            {open.taken_at ? `Taken ${fmtDay(open.taken_at)}` : `Added ${fmtDay(open.uploaded_at)}`}
            {open.uploaded_by ? ` · from ${open.uploaded_by}` : ""} · {open.width}×{open.height}
          </span>
        </>}>
          <div className="photo-big"><img src={open.display_url} alt={open.filename} /></div>
        </Sheet>
      )}
      {newAlbum && <NewAlbumSheet onClose={() => setNewAlbum(false)} onCreated={(id) => setAlbumId(id)} />}
    </div>
  );
}

function NewAlbumSheet({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const { api, toast } = useApp();
  const [name, setName] = useState("");
  async function create() {
    if (!name.trim()) return;
    try { const a = await api.createAlbum(name.trim()); onCreated(a.id); onClose(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't create album"); }
  }
  return (
    <Sheet title="New album" onClose={onClose} footer={<>
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <button className="btn" disabled={!name.trim()} onClick={create}>Create album</button>
    </>}>
      <div className="form">
        <div className="field-label">Name</div>
        <input className="input big" autoFocus placeholder="e.g. Summer 2026" value={name} maxLength={60}
          onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && create()} />
      </div>
    </Sheet>
  );
}
