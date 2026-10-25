import { useEffect, useRef } from "react";
import type { Audition } from "./audio";

export function Waveform({
  peaks = [],
  height = 120,
  duration = 0,
  position = 0,
  start = 0,
  end,
  seek,
  mini = false,
}: {
  peaks?: number[];
  height?: number;
  duration?: number;
  position?: number;
  start?: number;
  end?: number | null;
  seek?: (time: number) => void;
  mini?: boolean;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const draw = () => {
      const w = canvas.clientWidth,
        dpr = window.devicePixelRatio || 1;
      canvas.width = w * dpr;
      canvas.height = height * dpr;
      const c = canvas.getContext("2d");
      if (!c) return;
      c.scale(dpr, dpr);
      c.clearRect(0, 0, w, height);
      c.fillStyle = mini ? "#173832" : "#0b1716";
      c.fillRect(0, 0, w, height);
      if (!mini) {
        c.strokeStyle = "#24443c";
        c.lineWidth = 1;
        for (let i = 1; i < 4; i++) {
          c.beginPath();
          c.moveTo(0, (height * i) / 4);
          c.lineTo(w, (height * i) / 4);
          c.stroke();
        }
        for (let i = 1; i < 8; i++) {
          c.beginPath();
          c.moveTo((w * i) / 8, 0);
          c.lineTo((w * i) / 8, height);
          c.stroke();
        }
      }
      const step = Math.max(1, Math.floor(peaks.length / w));
      c.fillStyle = "#78c8ac";
      for (let i = 0; i < peaks.length; i += step) {
        const x = (i / peaks.length) * w,
          amp =
            Math.min(1, Math.abs(peaks[i])) * (height / 2 - (mini ? 1 : 12));
        c.fillRect(
          x,
          height / 2 - amp,
          Math.max(1, (w / peaks.length) * step - 0.5),
          Math.max(1, amp * 2),
        );
      }
      if (duration && !mini) {
        const left = (start / duration) * w,
          right = ((end ?? duration) / duration) * w;
        c.fillStyle = "#0c1419b0";
        c.fillRect(0, 0, left, height);
        c.fillRect(right, 0, w - right, height);
        c.strokeStyle = "#d4b26c";
        c.strokeRect(
          left + 0.5,
          0.5,
          Math.max(0, right - left - 1),
          height - 1,
        );
        if (position > 0) {
          c.strokeStyle = "#fff1be";
          c.beginPath();
          c.moveTo((position / duration) * w, 0);
          c.lineTo((position / duration) * w, height);
          c.stroke();
        }
      }
      if (!peaks.length) {
        c.fillStyle = "#82968e";
        c.font = "11px system-ui";
        c.textAlign = "center";
        c.fillText(
          mini ? "Belum dianalisis" : "Pilih clip untuk membaca waveform audio",
          w / 2,
          height / 2 + 4,
        );
      }
    };
    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(canvas);
    return () => ro.disconnect();
  }, [peaks, height, duration, position, start, end, mini]);
  return (
    <canvas
      ref={ref}
      className={"waveform " + (seek ? "seekable" : "")}
      style={{ height }}
      aria-label="Waveform amplitudo audio"
      role={seek ? "slider" : "img"}
      tabIndex={seek ? 0 : undefined}
      aria-valuemin={seek ? 0 : undefined}
      aria-valuemax={seek ? duration : undefined}
      aria-valuenow={seek ? position : undefined}
      onKeyDown={
        seek
          ? (e) => {
              if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
                e.preventDefault();
                seek(
                  Math.max(
                    0,
                    Math.min(
                      duration,
                      position + (e.key === "ArrowRight" ? 1 : -1) * 0.1,
                    ),
                  ),
                );
              }
            }
          : undefined
      }
      onClick={
        seek
          ? (e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              seek(((e.clientX - rect.left) / rect.width) * duration);
            }
          : undefined
      }
    />
  );
}
export function Spectrum({
  audition,
  playing,
}: {
  audition: Audition;
  playing: boolean;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let frame = 0;
    const draw = () => {
      const canvas = ref.current;
      if (!canvas) return;
      const w = canvas.clientWidth,
        h = 110,
        dpr = devicePixelRatio || 1;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      const c = canvas.getContext("2d");
      if (!c) return;
      c.scale(dpr, dpr);
      c.fillStyle = "#0b1716";
      c.fillRect(0, 0, w, h);
      const analyser = audition.analyser,
        nyquist = (audition.context?.sampleRate ?? 44100) / 2,
        maxHz = Math.min(20000, nyquist);
      if (analyser && playing) {
        const values = new Uint8Array(analyser.frequencyBinCount);
        analyser.getByteFrequencyData(values);
        const bars = 70;
        for (let i = 0; i < bars; i++) {
          const bin = Math.floor(
              ((20 * Math.pow(maxHz / 20, i / (bars - 1))) / nyquist) *
                values.length,
            ),
            v = values[Math.min(values.length - 1, bin)] / 255;
          c.fillStyle = i > 52 ? "#ccaf76" : "#69b99b";
          c.fillRect(
            (i * w) / bars,
            h - 12 - v * (h - 20),
            w / bars - 2,
            v * (h - 20),
          );
        }
      } else {
        c.fillStyle = "#82968e";
        c.font = "11px system-ui";
        c.textAlign = "center";
        c.fillText("Spectrum aktif saat audio diputar", w / 2, h / 2);
      }
      c.fillStyle = "#82968e";
      c.font = "10px system-ui";
      c.textAlign = "left";
      c.fillText("20 Hz", 8, h - 1);
      c.textAlign = "center";
      c.fillText(
        "1 kHz",
        (w * Math.log(1000 / 20)) / Math.log(maxHz / 20),
        h - 1,
      );
      c.textAlign = "right";
      c.fillText((maxHz / 1000).toFixed(0) + " kHz", w - 8, h - 1);
      if (playing && !document.hidden) frame = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(frame);
  }, [audition, playing]);
  return (
    <canvas
      ref={ref}
      className="spectrum"
      aria-label="Spectrum frekuensi audio saat playback"
    />
  );
}
export function Spectrogram({
  columns,
  sampleRate,
}: {
  columns: number[][];
  sampleRate: number;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !columns.length) return;
    canvas.width = columns.length;
    canvas.height = 160;
    const c = canvas.getContext("2d");
    if (!c) return;
    const data = c.createImageData(canvas.width, canvas.height);
    for (let x = 0; x < columns.length; x++)
      for (let y = 0; y < canvas.height; y++) {
        const b = Math.round(
            (1 - y / (canvas.height - 1)) ** 2 * (columns[x].length - 1),
          ),
          v = columns[x][b],
          i = (y * canvas.width + x) * 4;
        data.data[i] = 12 + v * 215;
        data.data[i + 1] = 24 + Math.pow(v, 0.7) * 165;
        data.data[i + 2] = 25 + v * 65;
        data.data[i + 3] = 255;
      }
    c.putImageData(data, 0, 0);
  }, [columns]);
  return (
    <div>
      <canvas
        ref={ref}
        className="spectrogram"
        role="img"
        aria-label={
          "Spectrogram channel 1, 0 sampai " +
          Math.round(sampleRate / 2) +
          " Hz"
        }
      />
      <div className="axis">
        <span>
          Channel 1 · 0–{Math.round(sampleRate / 2).toLocaleString()} Hz
        </span>
        <span>Waktu →</span>
      </div>
    </div>
  );
}
