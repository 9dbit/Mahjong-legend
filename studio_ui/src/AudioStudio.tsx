import { useEffect, useMemo, useRef, useState } from "react";
import type { Asset, Job, StudioConfig } from "./types";
import { assetURL, errorText, shorten } from "./api";
import {
  Badge,
  Empty,
  Field,
  Icon,
  Metric,
  Notice,
  NumberField,
  Section,
} from "./components";
import {
  Audition,
  cleanRecipe,
  clipMetrics,
  pcmWaveform,
  peaksFor,
  spectralColumns,
  type AudioRecipe,
} from "./audio";
import { Waveform, Spectrum, Spectrogram } from "./AudioGraphs";
const eventLabels: Record<string, string> = {
  tap: "Control tap",
  spin: "Spin start",
  stop: "Reel stop",
  break: "Tile break",
  cascade: "Cascade / refill",
  wild: "Gold → Wild",
  multiplier: "Multiplier change",
  scatter: "Scatter landing",
  bonus: "Bonus / retrigger",
  win: "Win",
  bigwin: "Big Win",
};
const recipeFields: {
  key: keyof AudioRecipe;
  label: string;
  min: number;
  max: number;
  step?: number;
}[] = [
  { key: "trim_start", label: "Trim mulai · s", min: 0, max: 120 },
  { key: "trim_end", label: "Trim akhir · s", min: 0, max: 120 },
  { key: "fade_in", label: "Fade in · s", min: 0, max: 30 },
  { key: "fade_out", label: "Fade out · s", min: 0, max: 30 },
  { key: "gain_db", label: "Gain · dB", min: -60, max: 12 },
  { key: "pan", label: "Pan · −1 L / +1 R", min: -1, max: 1, step: 0.05 },
  { key: "loop_start", label: "Loop mulai · s", min: 0, max: 120 },
  { key: "loop_end", label: "Loop akhir · s", min: 0, max: 120 },
  { key: "highpass_hz", label: "High-pass · Hz", min: 0, max: 20000 },
  { key: "lowpass_hz", label: "Low-pass · Hz", min: 0, max: 20000 },
  { key: "eq_low_db", label: "Low EQ · dB", min: -12, max: 12 },
  { key: "eq_mid_db", label: "Mid EQ · dB", min: -12, max: 12 },
  { key: "eq_high_db", label: "High EQ · dB", min: -12, max: 12 },
];
function metadataPeaks(asset?: Asset): number[] {
  const p = asset?.metadata.peaks ?? asset?.metadata.waveform;
  return Array.isArray(p)
    ? Array.isArray(p[0])
      ? (p as number[][])[0]
      : (p as number[])
    : [];
}
export default function AudioStudio({
  config,
  update,
  canEdit,
  assets,
  jobs,
  onUpload,
  onRender,
  onImport,
  onApplyMusic,
  isBusy,
  onError,
}: {
  config: StudioConfig;
  update: (recipe: (c: StudioConfig) => void) => void;
  canEdit: boolean;
  assets: Asset[];
  jobs: Job[];
  onUpload: (file: File, kind: string) => Promise<void>;
  onRender: (asset: Asset, recipe: Record<string, unknown>) => Promise<void>;
  onImport: (path: string) => Promise<void>;
  onApplyMusic: (mode: "base" | "bonus") => Promise<void>;
  isBusy: boolean;
  onError: (message: string) => void;
}) {
  const audio = useMemo(() => {
    const references = [
      ...Object.values(config.audio.events).map((b) => b.asset),
      ...Object.values(config.audio.music).map((m) => m?.asset),
    ].filter((p): p is string => !!p && p.startsWith("/"));
    const base: Asset[] = [...new Set(references)].map((path) => ({
      id: path,
      name: path.split("/").pop() || path,
      kind: "audio",
      status: "ready",
      url: path,
      metadata: {},
      is_baseline: true,
    }));
    // Keep READY originals visible as editable source rows. Uploads must
    // never disappear after the ingest worker changes status to Ready.
    // Only verified derivatives/baseline may be routed to game events/music.
    return [
      ...assets.filter((a) => a.kind === "audio"),
      ...base,
    ];
  }, [assets, config.audio]);
  const [selectedId, setSelectedId] = useState(""),
    [query, setQuery] = useState(""),
    [tab, setTab] = useState<"events" | "mixer" | "music">("events");
  const [recipe, setRecipe] = useState<AudioRecipe>({ ...cleanRecipe }),
    [undo, setUndo] = useState<AudioRecipe[]>([]),
    [redo, setRedo] = useState<AudioRecipe[]>([]);
  const [loading, setLoading] = useState(false),
    [playing, setPlaying] = useState(false),
    [raw, setRaw] = useState(false),
    [loop, setLoop] = useState(false),
    [position, setPosition] = useState(0),
    [volume, setVolume] = useState(0.5),
    [zoom, setZoom] = useState(1);
  const [buffer, setBuffer] = useState<AudioBuffer | null>(null),
    [peaks, setPeaks] = useState<number[]>([]),
    [spectrogram, setSpectrogram] = useState<number[][] | null>(null),
    [analyses, setAnalyses] = useState<
      Record<string, { peaks: number[]; duration: number }>
    >({});
  const nativePlayers = useRef(new Set<HTMLMediaElement>());
  const audition = useRef<Audition | null>(null);
  if (!audition.current) audition.current = new Audition();
  const player = audition.current;
  const selected = audio.find((a) => a.id === selectedId);
  const selectedJob = jobs.find((j) => j.source_asset_id === selectedId && (j.kind === "ingest" || j.kind === "render"));
  const rawAsset = selected?.original_id
    ? audio.find(
        (a) =>
          a.original_id === selected.original_id &&
          a.recipe &&
          Number(a.recipe.trim_start ?? 0) === 0 &&
          Number(a.recipe.trim_end ?? a.metadata.duration) ===
            Number(a.metadata.duration) &&
          [
            "gain_db",
            "pan",
            "fade_in",
            "fade_out",
            "highpass_hz",
            "lowpass_hz",
            "eq_low_db",
            "eq_mid_db",
            "eq_high_db",
          ].every((k) => !a.recipe?.[k]),
      )
    : selected;
  const duration =
    buffer?.duration ??
    selected?.metadata.duration ??
    selected?.metadata.duration_seconds ??
    0;
  const metrics = useMemo(
    () => (buffer ? clipMetrics(buffer) : null),
    [buffer],
  );
  useEffect(() => {
    if (selectedId && audio.some((a) => a.id === selectedId)) return;
    const next = audio.find((a) => a.original_id === selectedId) || audio[0];
    if (next?.id !== selectedId) setSelectedId(next?.id || "");
  }, [audio, selectedId]);
  useEffect(() => {
    const abort = new AbortController();
    void (async () => {
      for (const a of audio.filter(
        (a) => a.is_baseline && a.url.endsWith(".wav"),
      )) {
        if (abort.signal.aborted) return;
        try {
          const response = await fetch(a.url, {
            signal: abort.signal,
            credentials: "same-origin",
          });
          if (!response.ok) continue;
          const analysis = pcmWaveform(await response.arrayBuffer());
          if (analysis && !abort.signal.aborted)
            setAnalyses((prev) => ({ ...prev, [a.id]: analysis }));
        } catch {}
      }
    })();
    return () => abort.abort();
  }, [audio.map((a) => a.id).join("|")]);
  useEffect(() => {
    const nativePlay = (event: Event) => {
      if (event.target instanceof HTMLMediaElement) {
        for (const media of nativePlayers.current)
          if (media !== event.target) media.pause();
        nativePlayers.current.add(event.target);
        player.stop();
        setPlaying(false);
      }
    };
    const stop = () => {
      if (document.hidden) {
        player.stop();
        setPlaying(false);
        for (const media of nativePlayers.current) media.pause();
      }
    };
    document.addEventListener("play", nativePlay, true);
    document.addEventListener("visibilitychange", stop);
    return () => {
      document.removeEventListener("play", nativePlay, true);
      document.removeEventListener("visibilitychange", stop);
      for (const media of nativePlayers.current) media.pause();
      nativePlayers.current.clear();
      player.dispose();
    };
  }, [player]);
  useEffect(() => {
    for (const media of nativePlayers.current) media.pause();
    setBuffer(null);
    setSpectrogram(null);
    setPosition(0);
    setPlaying(false);
    setUndo([]);
    setRedo([]);
    setRecipe({ ...cleanRecipe });
    setPeaks(metadataPeaks(selected));
    setLoading(false);
    if (!selected || selected.status !== "ready") return;
    // Original uploads are intentionally private (the content endpoint returns
    // 403). Rendering is a server-side job and must remain enabled without
    // trying to decode that private original in the browser.
    if (!selected.is_derivative && !selected.is_baseline) return;
    if (!rawAsset) {
      onError(
        "Neutral source derivative belum tersedia. Dengarkan hasil render; import kembali original untuk melanjutkan editing.",
      );
      return;
    }
    let disposed = false;
    setLoading(true);
    void player
      .load(rawAsset.url)
      .then((b) => {
        if (!disposed && b) {
          setBuffer(b);
          const waveform = peaksFor(b);
          setPeaks(waveform);
          setAnalyses((prev) => ({
            ...prev,
            [rawAsset.id]: { peaks: waveform, duration: b.duration },
          }));
          setRecipe({
            ...cleanRecipe,
            trim_end: b.duration,
            ...Object.fromEntries(
              Object.entries(selected.recipe ?? {}).filter(
                ([key]) => key in cleanRecipe,
              ),
            ),
          });
        }
      })
      .catch((e) => {
        if (!disposed) onError(errorText(e));
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
      player.stop();
      player.epoch++;
    };
  }, [selected?.id, selected?.url, rawAsset?.url, player]);
  useEffect(() => {
    player.onended = () => {
      setPlaying(false);
      setPosition(0);
    };
    if (!playing) return;
    const id = setInterval(() => setPosition(player.time()), 70);
    return () => clearInterval(id);
  }, [playing, player]);
  function change(key: keyof AudioRecipe, value: number | null) {
    setUndo((old) => [...old.slice(-29), { ...recipe }]);
    setRedo([]);
    setRecipe((r) => {
      const n = { ...r, [key]: value };
      if (key === "loop_start" || key === "loop_end") {
        if (value === null) {
          n.loop_start = null;
          n.loop_end = null;
        } else {
          n.loop_start ??= 0;
          n.loop_end ??= (n.trim_end ?? duration) - n.trim_start;
        }
      }
      return n;
    });
    if (playing) {
      player.stop();
      setPlaying(false);
    }
  }
  async function togglePlay() {
    try {
      document.querySelectorAll("audio").forEach((a) => a.pause());
      await player.unlock();
      if (playing) {
        setPosition(player.time());
        player.stop();
        setPlaying(false);
        return;
      }
      player.start(recipe, position, raw, loop, volume);
      setPlaying(true);
    } catch (e) {
      onError(errorText(e));
    }
  }
  function seek(time: number) {
    setPosition(time);
    if (playing) {
      try {
        player.start(recipe, time, raw, loop, volume);
      } catch (e) {
        onError(errorText(e));
        setPlaying(false);
      }
    }
  }
  const usage = (id: string) =>
    Object.entries(config.audio.events)
      .filter(([, b]) => b.asset === id)
      .map(([key]) => eventLabels[key] || key)
      .concat(
        Object.entries(config.audio.music)
          .filter(([, m]) => m?.asset === id)
          .map(([key]) => "BGM " + key),
      );
  const assignOptions = () => (
    <>
      <option value="">No sound</option>
      {audio
        .filter((a) => a.status === "ready" && (a.is_derivative || a.is_baseline))
        .map((a) => (
          <option value={a.id} key={a.id}>
            {a.name}
          </option>
        ))}
    </>
  );
  return (
    <>
      <Section
        eyebrow="SOUND DESIGN WORKSPACE"
        title="Audio Studio"
        description="Original tetap utuh. Dengarkan derivative hasil render sebelum mengikatnya ke event."
        actions={
          <label className={"button " + (!canEdit ? "disabled" : "")}>
            <Icon name="upload" />
            Upload audio
            <input
              hidden
              type="file"
              disabled={!canEdit}
              accept=".wav,.wave,.mp3,.m4a,.mp4,.ogg,.flac,audio/wav,audio/mpeg,audio/mp4,audio/x-m4a,audio/ogg,audio/flac"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f && f.size > 32 * 1024 * 1024) onError("Audio melebihi batas 32 MiB.");
                else if (f) void onUpload(f, "audio");
                e.target.value = "";
              }}
            />
          </label>
        }
      >
        <div className="audio-workspace">
          <aside className="audio-library">
            <input
              className="search"
              placeholder="Cari audio…"
              aria-label="Cari audio"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <div className="library-count">
              {audio.length} audio assets <span>ORIGINAL + RENDERS</span>
            </div>
            {audio
              .filter((a) => a.name.toLowerCase().includes(query.toLowerCase()))
              .map((a) => (
                <button
                  key={a.id}
                  data-asset-id={a.id}
                  className={
                    "audio-item " + (a.id === selectedId ? "selected" : "")
                  }
                  onClick={() => setSelectedId(a.id)}
                >
                  <div>
                    <strong>{a.name}</strong>
                    <Badge tone={a.status === "ready" ? "jade" : ""}>
                      {a.status}
                    </Badge>
                  </div>
                  <Waveform
                    peaks={analyses[a.id]?.peaks ?? metadataPeaks(a)}
                    height={30}
                    mini
                  />
                  <span>
                    {(analyses[a.id]?.duration ??
                      a.metadata.duration ??
                      a.metadata.duration_seconds) === undefined
                      ? "—"
                      : Number(
                          analyses[a.id]?.duration ??
                            a.metadata.duration ??
                            a.metadata.duration_seconds,
                        ).toFixed(2)}
                    s <i>·</i> {usage(a.id).join(", ") || "Unassigned"}
                  </span>
                </button>
              ))}
            {!audio.length && (
              <Empty icon="audio" title="Belum ada audio">
                Upload audio untuk waveform, editing, dan pemetaan event.
              </Empty>
            )}
          </aside>
          <div className="audio-editor">
            {selected ? (
              <>
                <div className="clip-heading">
                  <div>
                    <p className="eyebrow">
                      {selected.is_baseline
                        ? "BASELINE AUDIO"
                        : selected.original_id
                          ? "RENDERED DERIVATIVE"
                          : "SOURCE AUDIO"}
                    </p>
                    <h3>{selected.name}</h3>
                    <p className="muted small">
                      {buffer?.sampleRate ??
                        selected.metadata.sample_rate ??
                        "—"}{" "}
                      Hz ·{" "}
                      {buffer?.numberOfChannels ??
                        selected.metadata.channels ??
                        "—"}{" "}
                      channel · {shorten(selected.sha256)}
                    </p>
                  </div>
                  <Badge tone="jade">
                    {loading ? "Decoding…" : selected.status}
                  </Badge>
                </div>
                {!selected.is_derivative && !selected.is_baseline && (
                  <div className={"notice " + (selected.status === "failed" ? "danger" : "jade")} role="status">
                    {selected.status === "failed"
                      ? `Upload gagal diproses: ${selectedJob?.error || "Periksa format atau durasi file, lalu upload ulang."}`
                      : `Upload diterima. ${selectedJob?.status === "running" ? `Worker ${Math.round(selectedJob.progress || 0)}%` : "Menunggu worker memproses audio."}`}
                  </div>
                )}
                {!selected.is_baseline && (
                  <p className="muted small">
                    Editor: neutral source. Render terpilih:{" "}
                    {Number(selected.metadata.duration ?? 0).toFixed(3)} s.
                  </p>
                )}
                <div className="wave-toolbar">
                  <span>WAVEFORM</span>
                  <div className="inline">
                    <label className="inline small">
                      Zoom{" "}
                      <select
                        aria-label="Zoom waveform"
                        value={zoom}
                        onChange={(e) => setZoom(Number(e.target.value))}
                      >
                        {[1, 2, 4, 8].map((v) => (
                          <option value={v} key={v}>
                            {v}×
                          </option>
                        ))}
                      </select>
                    </label>
                    <button
                      className="icon-button"
                      aria-label="Undo audio recipe"
                      disabled={!undo.length}
                      onClick={() => {
                        const prev = undo.at(-1)!;
                        setRedo([...redo, recipe]);
                        setRecipe(prev);
                        setUndo(undo.slice(0, -1));
                        player.stop();
                        setPlaying(false);
                      }}
                    >
                      <Icon name="undo" size={16} />
                    </button>
                    <button
                      className="icon-button"
                      aria-label="Redo audio recipe"
                      disabled={!redo.length}
                      onClick={() => {
                        setUndo([...undo, recipe]);
                        setRecipe(redo.at(-1)!);
                        setRedo(redo.slice(0, -1));
                        player.stop();
                        setPlaying(false);
                      }}
                    >
                      <Icon name="redo" size={16} />
                    </button>
                  </div>
                </div>
                <div className="wave-scroll">
                  <div style={{ width: `${zoom * 100}%` }}>
                    <Waveform
                      peaks={peaks}
                      height={158}
                      duration={duration}
                      position={position}
                      start={raw ? 0 : recipe.trim_start}
                      end={raw ? duration : recipe.trim_end}
                      seek={seek}
                    />
                  </div>
                </div>
                <div className="axis">
                  <span>0:00.000</span>
                  <span>{duration.toFixed(3)} s</span>
                </div>
                <div className="transport">
                  <button
                    className="button primary"
                    disabled={loading || !buffer}
                    onClick={() => void togglePlay()}
                  >
                    <Icon name={playing ? "pause" : "play"} size={18} />
                    {playing ? "Pause" : "Play"}
                  </button>
                  <button
                    className="icon-button"
                    aria-label="Stop audio preview"
                    onClick={() => {
                      player.stop();
                      setPlaying(false);
                      setPosition(0);
                    }}
                  >
                    <Icon name="stop" size={18} />
                  </button>
                  <span className="timecode">
                    {position.toFixed(3)}{" "}
                    <small>/ {duration.toFixed(3)} s</small>
                  </span>
                  <label className="check-label">
                    <input
                      type="checkbox"
                      checked={loop}
                      onChange={(e) => {
                        setLoop(e.target.checked);
                        player.stop();
                        setPlaying(false);
                      }}
                    />
                    Loop
                  </label>
                  <div className="segmented compact">
                    <button
                      className={raw ? "active" : ""}
                      onClick={() => {
                        setRaw(true);
                        player.stop();
                        setPlaying(false);
                      }}
                    >
                      A · Raw
                    </button>
                    <button
                      className={!raw ? "active" : ""}
                      onClick={() => {
                        setRaw(false);
                        player.stop();
                        setPlaying(false);
                      }}
                    >
                      B · Recipe
                    </button>
                  </div>
                </div>
                <Field label="Audition level · hanya Studio">
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.01}
                    value={volume}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      setVolume(v);
                      if (player.output) player.output.gain.value = v;
                    }}
                  />
                </Field>
                {!selected.is_baseline && (
                  <div className="rendered-audition">
                    <span className="eyebrow">
                      LISTEN TO EXACT RENDERED FILE
                    </span>
                    <audio
                      className="native-audio"
                      src={selected.url}
                      controls
                      preload="none"
                      onPlay={() => {
                        player.stop();
                        setPlaying(false);
                      }}
                      aria-label="Listen rendered derivative"
                    />
                  </div>
                )}
                <div className="audio-metrics">
                  <Metric
                    label="Source peak"
                    value={metrics ? metrics.peak.toFixed(1) + " dBFS" : "—"}
                  />
                  <Metric
                    label="Source RMS"
                    value={metrics ? metrics.rms.toFixed(1) + " dBFS" : "—"}
                  />
                  <Metric
                    label="LUFS"
                    value={
                      selected.metadata.lufs != null
                        ? Number(selected.metadata.lufs).toFixed(1)
                        : "N/A"
                    }
                    detail="Analisis server"
                  />
                  <Metric
                    label="True peak"
                    value={
                      (selected.metadata.true_peak_db ??
                        selected.metadata.true_peak_dbfs) != null
                        ? Number(
                            selected.metadata.true_peak_db ??
                              selected.metadata.true_peak_dbfs,
                          ).toFixed(1) + " dBTP"
                        : "N/A"
                    }
                  />
                </div>
                <div className="graph-heading">
                  <span>LIVE FREQUENCY SPECTRUM</span>
                  <Badge>FFT 1024</Badge>
                </div>
                <Spectrum audition={player} playing={playing} />
                <div className="graph-heading">
                  <span>SPECTROGRAM</span>
                  <button
                    className="text-button"
                    disabled={!buffer || loading}
                    onClick={() => {
                      if (buffer) setSpectrogram(spectralColumns(buffer));
                    }}
                  >
                    {spectrogram ? "Hitung ulang" : "Analisis clip"}
                  </button>
                </div>
                {spectrogram && buffer ? (
                  <Spectrogram
                    columns={spectrogram}
                    sampleRate={buffer.sampleRate}
                  />
                ) : (
                  <div className="graph-placeholder">
                    Analisis frekuensi terhadap waktu dihitung saat diminta.
                  </div>
                )}
              </>
            ) : (
              <Empty title="Pilih clip" icon="audio">
                Waveform dan analisis berasal dari audio yang dipilih.
              </Empty>
            )}
          </div>
          <aside className="audio-inspector">
            <p className="eyebrow">NON-DESTRUCTIVE RECIPE</p>
            <h3>Clip inspector</h3>
            {selected ? (
              <>
                <div className="form-grid">
                  {recipeFields.map(({ key, label, min, max, step }) => (
                    <Field label={label} key={key}>
                      <input
                        type="number"
                        value={recipe[key] ?? ""}
                        min={min}
                        max={max}
                        step={step ?? "any"}
                        onChange={(e) =>
                          change(
                            key,
                            e.target.value === "" &&
                              (key === "trim_end" ||
                                key === "loop_end" ||
                                key === "loop_start")
                              ? null
                              : Number(e.target.value),
                          )
                        }
                      />
                    </Field>
                  ))}
                </div>
                <button
                  className="button primary full"
                  aria-label={selected.is_baseline ? "Import baseline audio for editing" : "Render audio derivative"}
                  disabled={!canEdit || selected.status !== "ready" || isBusy}
                  title={!canEdit ? "Role ini tidak memiliki izin edit" :
                    selected.status !== "ready" ? "Proses ingest audio sampai Ready" :
                    selected.is_baseline ? "Import baseline ke Studio, tanpa perlu decode preview" :
                    "Render di worker berdasarkan original; preview browser bersifat opsional"}
                  onClick={() =>
                    void (selected.is_baseline
                      ? onImport(selected.id)
                      : onRender(selected, {
                          ...recipe,
                          trim_end: recipe.trim_end ?? duration,
                        }))
                  }
                >
                  {selected.is_baseline
                    ? "Import untuk editing"
                    : "Render derivative"}
                </button>
                {selected.status === "ready" && !buffer && !loading && (
                  <p className="muted small" role="status">
                    {selected.is_baseline
                      ? "Import tetap dapat digunakan meskipun preview audio browser tidak tersedia."
                      : "Decode preview tidak tersedia. Render server tetap bisa dijalankan; hasil siap akan muncul di library."}
                  </p>
                )}
                <button
                  className="button subtle full"
                  onClick={() => {
                    setUndo([...undo, recipe]);
                    setRecipe({ ...cleanRecipe, trim_end: duration });
                    setRedo([]);
                    player.stop();
                    setPlaying(false);
                  }}
                >
                  Reset recipe
                </button>
                <Notice>
                  Loop dihitung relatif terhadap clip setelah trim. Renderer
                  server menentukan file final. Pilih hasil render dari library
                  untuk mendengar byte yang akan diterbitkan.
                </Notice>
              </>
            ) : (
              <p className="muted small">
                Pilih audio untuk trim, gain, loop, fade dan EQ.
              </p>
            )}
          </aside>
        </div>
      </Section>
      <Section
        title="Game audio routing"
        description="Perubahan mixer dan event disimpan sebagai bagian dari draft."
        actions={
          <div className="segmented">
            {(["events", "mixer", "music"] as const).map((t) => (
              <button
                key={t}
                className={tab === t ? "active" : ""}
                onClick={() => setTab(t)}
              >
                {t === "events"
                  ? "Event map"
                  : t === "mixer"
                    ? "Mixer"
                    : "Background music"}
              </button>
            ))}
          </div>
        }
      >
        {tab === "events" && (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Event</th>
                  <th>Clip</th>
                  <th>Bus</th>
                  <th>Gain</th>
                  <th>Aktif</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(config.audio.events).map(([event, binding]) => (
                  <tr key={event}>
                    <td>
                      <strong>{eventLabels[event] || event}</strong>
                      <small className="block muted">{event}</small>
                    </td>
                    <td>
                      <select
                        aria-label={"Clip " + event}
                        disabled={!canEdit}
                        value={binding.asset ?? ""}
                        onChange={(e) =>
                          update((c) => {
                            c.audio.events[event].asset =
                              e.target.value || null;
                            c.audio.events[event].enabled = !!e.target.value;
                          })
                        }
                      >
                        {assignOptions()}
                      </select>
                    </td>
                    <td>
                      <select
                        aria-label={"Bus " + event}
                        disabled={!canEdit}
                        value={binding.bus}
                        onChange={(e) =>
                          update((c) => {
                            c.audio.events[event].bus = e.target.value;
                          })
                        }
                      >
                        {Object.keys(config.audio.buses)
                          .filter((bus) => bus !== "music")
                          .map((bus) => (
                            <option key={bus}>{bus}</option>
                          ))}
                      </select>
                    </td>
                    <td>
                      <input
                        className="narrow"
                        aria-label={"Gain " + event}
                        type="number"
                        min="0"
                        max="2"
                        step=".05"
                        disabled={!canEdit}
                        value={binding.gain}
                        onChange={(e) =>
                          update((c) => {
                            c.audio.events[event].gain = Number(e.target.value);
                          })
                        }
                      />
                    </td>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={"Aktif " + event}
                        disabled={!canEdit || !binding.asset}
                        checked={binding.enabled}
                        onChange={(e) =>
                          update((c) => {
                            c.audio.events[event].enabled = e.target.checked;
                          })
                        }
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {tab === "mixer" && (
          <>
            <div className="mixer">
              <div className="mixer-strip master">
                <span>MASTER OUTPUT</span>
                <strong>{Number(config.audio.output_gain).toFixed(2)}×</strong>
                <input
                  type="range"
                  min={0}
                  max={2}
                  step={0.01}
                  disabled={!canEdit}
                  aria-label="Master output gain"
                  value={config.audio.output_gain}
                  onChange={(e) =>
                    update((c) => {
                      c.audio.output_gain = Number(e.target.value);
                    })
                  }
                />
                <small>Baseline boost 1,30×</small>
              </div>
              {Object.entries(config.audio.buses).map(([bus, gain]) => (
                <div className="mixer-strip" key={bus}>
                  <span>{bus.toUpperCase()}</span>
                  <strong>{Number(gain).toFixed(2)}×</strong>
                  <input
                    type="range"
                    min={0}
                    max={2}
                    step={0.01}
                    disabled={!canEdit}
                    aria-label={"Gain bus " + bus}
                    value={gain}
                    onChange={(e) =>
                      update((c) => {
                        c.audio.buses[bus] = Number(e.target.value);
                      })
                    }
                  />
                  <button
                    className={"button subtle " + (gain === 0 ? "active" : "")}
                    disabled={!canEdit}
                    onClick={() =>
                      update((c) => {
                        c.audio.buses[bus] = gain === 0 ? 1 : 0;
                      })
                    }
                  >
                    {gain === 0 ? "Unmute" : "Mute"}
                  </button>
                </div>
              ))}
            </div>
            <Notice>
              Preferensi volume dan mute pemain tetap menjadi kontrol akhir.
              Gain 1,30× diimpor sekali; slider ini tidak menambahkan boost
              tersembunyi.
            </Notice>
          </>
        )}
        {tab === "music" && (
          <div className="two-column">
            {(["base", "bonus"] as const).map((mode) => {
              const track = config.audio.music[mode];
              return (
                <div className="music-track" key={mode}>
                  <h3>{mode === "base" ? "Base game" : "Bonus game"}</h3>
                  <Field label="Track">
                    <select
                      disabled={!canEdit}
                      value={track?.asset ?? ""}
                      onChange={(e) =>
                        update((c) => {
                          const next = e.target.value
                            ? {
                                asset: e.target.value,
                                gain: track?.gain ?? 1,
                                loop_start: track?.loop_start ?? 0,
                                loop_end: track?.loop_end ?? null,
                              }
                            : null;
                          c.audio.music[mode] = next;
                        })
                      }
                    >
                      {assignOptions()}
                    </select>
                  </Field>
                  {track && (
                    <div className="form-grid">
                      <NumberField
                        disabled={!canEdit}
                        label="Gain"
                        min={0}
                        max={2}
                        value={track.gain}
                        onChange={(v) =>
                          update((c) => {
                            c.audio.music[mode]!.gain = v;
                          })
                        }
                      />
                      <NumberField
                        disabled={!canEdit}
                        label="Loop mulai · s"
                        min={0}
                        value={track.loop_start}
                        onChange={(v) =>
                          update((c) => {
                            c.audio.music[mode]!.loop_start = v;
                          })
                        }
                      />
                      <Field label="Loop akhir · s" hint="Kosong: akhir clip">
                        <input
                          disabled={!canEdit}
                          type="number"
                          min="0"
                          step="any"
                          value={track.loop_end ?? ""}
                          onChange={(e) =>
                            update((c) => {
                              c.audio.music[mode]!.loop_end =
                                e.target.value === ""
                                  ? null
                                  : Number(e.target.value);
                            })
                          }
                        />
                      </Field>
                    </div>
                  )}
                  <button
                    className="button primary full"
                    type="button"
                    aria-label={"Apply " + mode + " background music"}
                    disabled={!canEdit || isBusy}
                    title={!canEdit ? "Perlu izin edit Game Studio" : isBusy ? "Selesaikan proses sebelumnya" : "Simpan dan validasi pengaturan musik ke draft"}
                    onClick={() => void onApplyMusic(mode)}
                  >
                    {isBusy ? "Processing…" : "Apply to draft"}
                  </button>
                  <p className="muted small" role="note">
                    Apply menyimpan dan memvalidasi draft. Untuk mengubah musik
                    pada game live, klik Publish setelah validasi lulus.
                  </p>
                  {track?.asset && (
                    <audio
                      className="native-audio"
                      controls
                      preload="none"
                      src={assetURL(track.asset, assets)}
                      aria-label={"Audition rendered " + mode + " music"}
                    />
                  )}
                  <p className="muted small">
                    {mode === "bonus"
                      ? "Kosong memakai perilaku musik base."
                      : "Dengarkan akhir/awal loop pada perangkat target."}
                  </p>
                </div>
              );
            })}
          </div>
        )}
      </Section>
    </>
  );
}
