export type AudioRecipe = {
  trim_start: number;
  trim_end: number | null;
  loop_start: number | null;
  loop_end: number | null;
  fade_in: number;
  fade_out: number;
  gain_db: number;
  pan: number;
  highpass_hz: number;
  lowpass_hz: number;
  eq_low_db: number;
  eq_mid_db: number;
  eq_high_db: number;
};
export const cleanRecipe: AudioRecipe = {
  trim_start: 0,
  trim_end: null,
  loop_start: null,
  loop_end: null,
  fade_in: 0,
  fade_out: 0,
  gain_db: 0,
  pan: 0,
  highpass_hz: 0,
  lowpass_hz: 0,
  eq_low_db: 0,
  eq_mid_db: 0,
  eq_high_db: 0,
};
export function peaksFor(buffer: AudioBuffer, count = 600): number[] {
  const channels = Array.from({ length: buffer.numberOfChannels }, (_, c) =>
    buffer.getChannelData(c),
  );
  const block = Math.max(1, Math.floor(buffer.length / count));
  return Array.from({ length: Math.min(count, buffer.length) }, (_, i) => {
    let peak = 0;
    for (const channel of channels)
      for (let j = i * block; j < Math.min((i + 1) * block, buffer.length); j++)
        peak = Math.max(peak, Math.abs(channel[j]));
    return peak;
  });
}
export function clipMetrics(buffer: AudioBuffer) {
  let peak = 0,
    total = 0;
  for (let c = 0; c < buffer.numberOfChannels; c++) {
    const a = buffer.getChannelData(c);
    for (let i = 0; i < a.length; i++) {
      peak = Math.max(peak, Math.abs(a[i]));
      total += a[i] * a[i];
    }
  }
  return {
    peak: 20 * Math.log10(peak || 1e-10),
    rms:
      20 *
      Math.log10(
        Math.sqrt(total / (buffer.length * buffer.numberOfChannels)) || 1e-10,
      ),
  };
}
export class Audition {
  context: AudioContext | null = null;
  buffer: AudioBuffer | null = null;
  analyser: AnalyserNode | null = null;
  source: AudioBufferSourceNode | null = null;
  output: GainNode | null = null;
  private nodes: AudioNode[] = [];
  private started = 0;
  private offset = 0;
  private loopStart = 0;
  private loopEnd = 0;
  private looping = false;
  playing = false;
  epoch = 0;
  onended?: () => void;
  async unlock() {
    if (!this.context) this.context = new AudioContext();
    if (this.context.state !== "running") await this.context.resume();
  }
  async load(url: string) {
    this.stop();
    const generation = ++this.epoch;
    if (!this.context) this.context = new AudioContext();
    const r = await fetch(url, { credentials: "same-origin" });
    if (!r.ok) throw Error("Audio tidak dapat dimuat (" + r.status + ").");
    const bytes = await r.arrayBuffer();
    if (bytes.byteLength > 32 * 1024 * 1024)
      throw Error("Audio melebihi batas preview 32 MiB.");
    const b = await this.context.decodeAudioData(bytes);
    if (generation !== this.epoch) return null;
    this.buffer = b;
    return b;
  }
  start(
    recipe: AudioRecipe,
    position: number,
    raw: boolean,
    loop: boolean,
    volume: number,
  ) {
    if (!this.context || !this.buffer)
      throw Error("Pilih audio yang siap diputar.");
    this.stop();
    const ctx = this.context,
      b = this.buffer,
      start = Math.max(0, raw ? 0 : recipe.trim_start),
      end = Math.min(
        b.duration,
        raw ? b.duration : (recipe.trim_end ?? b.duration),
      );
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start)
      throw Error("Trim akhir harus sesudah trim awal.");
    const offset = Math.max(start, Math.min(position, end - 0.00001));
    const source = ctx.createBufferSource();
    source.buffer = b;
    this.source = source;
    let node: AudioNode = source;
    this.nodes = [];
    const connect = (next: AudioNode) => {
      node.connect(next);
      node = next;
      this.nodes.push(next);
    };
    if (!raw) {
      const filter = (type: BiquadFilterType, freq: number, gain = 0) => {
        const n = ctx.createBiquadFilter();
        n.type = type;
        n.frequency.value = freq;
        n.gain.value = gain;
        n.Q.value = 0.707;
        connect(n);
      };
      if (recipe.highpass_hz > 0) filter("highpass", recipe.highpass_hz);
      if (recipe.lowpass_hz > 0)
        filter("lowpass", Math.min(recipe.lowpass_hz, ctx.sampleRate / 2 - 1));
      filter("peaking", 120, recipe.eq_low_db);
      filter("peaking", 1000, recipe.eq_mid_db);
      filter("peaking", 8000, recipe.eq_high_db);
      if (recipe.pan) {
        const splitter = ctx.createChannelSplitter(b.numberOfChannels),
          merger = ctx.createChannelMerger(2),
          left = ctx.createGain(),
          right = ctx.createGain();
        left.gain.value =
          b.numberOfChannels === 1
            ? Math.cos(((recipe.pan + 1) * Math.PI) / 4)
            : 1 - Math.max(0, recipe.pan);
        right.gain.value =
          b.numberOfChannels === 1
            ? Math.sin(((recipe.pan + 1) * Math.PI) / 4)
            : 1 + Math.min(0, recipe.pan);
        node.connect(splitter);
        splitter.connect(left, 0);
        splitter.connect(right, b.numberOfChannels === 1 ? 0 : 1);
        left.connect(merger, 0, 0);
        right.connect(merger, 0, 1);
        node = merger;
        this.nodes.push(splitter, left, right, merger);
      }
    }
    const gain = ctx.createGain();
    const level = raw ? 1 : Math.pow(10, recipe.gain_db / 20);
    gain.gain.value = level;
    connect(gain);
    if (!raw && !loop) {
      const now = ctx.currentTime,
        remaining = end - offset,
        fadeIn = Math.min(recipe.fade_in, remaining),
        fadeOut = Math.min(recipe.fade_out, remaining);
      if (fadeIn > 0 && offset <= start + 0.001) {
        gain.gain.setValueAtTime(0, now);
        gain.gain.linearRampToValueAtTime(level, now + fadeIn);
      }
      if (fadeOut > 0) {
        gain.gain.setValueAtTime(
          level,
          now + Math.max(fadeIn, remaining - fadeOut),
        );
        gain.gain.linearRampToValueAtTime(0, now + remaining);
      }
    }
    this.analyser = ctx.createAnalyser();
    this.analyser.fftSize = 1024;
    connect(this.analyser);
    this.output = ctx.createGain();
    this.output.gain.value = volume;
    connect(this.output);
    node.connect(ctx.destination);
    this.loopStart = Math.max(
      start,
      raw ? start : start + (recipe.loop_start ?? 0),
    );
    this.loopEnd = Math.min(
      end,
      raw ? end : recipe.loop_end === null ? end : start + recipe.loop_end,
    );
    this.looping = loop && this.loopEnd > this.loopStart;
    source.loop = this.looping;
    if (this.looping) {
      source.loopStart = this.loopStart;
      source.loopEnd = this.loopEnd;
    }
    this.offset = offset;
    this.started = ctx.currentTime;
    this.playing = true;
    source.onended = () => {
      if (this.source === source) {
        this.playing = false;
        this.onended?.();
      }
    };
    if (this.looping) source.start(0, offset);
    else source.start(0, offset, end - offset);
  }
  time() {
    if (!this.context || !this.playing) return this.offset;
    let pos = this.offset + this.context.currentTime - this.started;
    if (this.looping && pos >= this.loopEnd)
      pos =
        this.loopStart +
        ((pos - this.loopStart) % (this.loopEnd - this.loopStart));
    return pos;
  }
  stop() {
    if (this.playing) this.offset = this.time();
    if (this.source) {
      this.source.onended = null;
      try {
        this.source.stop();
      } catch {}
      this.source.disconnect();
      this.source = null;
    }
    for (const node of this.nodes) node.disconnect();
    this.nodes = [];
    this.playing = false;
  }
  dispose() {
    this.stop();
    this.epoch++;
    this.buffer = null;
    if (this.context) void this.context.close();
    this.context = null;
  }
}
// Bounded, on-demand Hann-window FFT. Input is the decoded audio, never an illustrative waveform.
export function spectralColumns(
  buffer: AudioBuffer,
  columns = 320,
  size = 512,
) {
  const samples = buffer.getChannelData(0),
    out: number[][] = [];
  for (let col = 0; col < columns; col++) {
    const offset = Math.floor(
      (col / Math.max(1, columns - 1)) * Math.max(0, samples.length - size),
    );
    const re = new Float64Array(size),
      im = new Float64Array(size);
    for (let i = 0; i < size; i++)
      re[i] =
        (samples[offset + i] || 0) *
        (0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (size - 1)));
    for (let i = 1, j = 0; i < size; i++) {
      let bit = size >> 1;
      for (; j & bit; bit >>= 1) j ^= bit;
      j ^= bit;
      if (i < j) {
        const v = re[i];
        re[i] = re[j];
        re[j] = v;
      }
    }
    for (let len = 2; len <= size; len <<= 1) {
      const ang = (-2 * Math.PI) / len;
      for (let i = 0; i < size; i += len)
        for (let j = 0; j < len / 2; j++) {
          const wr = Math.cos(ang * j),
            wi = Math.sin(ang * j),
            a = i + j,
            b = a + len / 2,
            vr = re[b] * wr - im[b] * wi,
            vi = re[b] * wi + im[b] * wr;
          re[b] = re[a] - vr;
          im[b] = im[a] - vi;
          re[a] += vr;
          im[a] += vi;
        }
    }
    out.push(
      Array.from({ length: size / 2 }, (_, i) =>
        Math.max(
          0,
          Math.min(
            1,
            (20 * Math.log10(Math.hypot(re[i], im[i]) / size + 1e-8) + 90) / 80,
          ),
        ),
      ),
    );
  }
  return out;
}

export function pcmWaveform(
  bytes: ArrayBuffer,
  count = 240,
): { peaks: number[]; duration: number } | null {
  if (bytes.byteLength < 44 || bytes.byteLength > 512 * 1024) return null;
  const view = new DataView(bytes);
  const tag = (i: number) =>
    String.fromCharCode(...new Uint8Array(bytes, i, 4));
  if (tag(0) !== "RIFF" || tag(8) !== "WAVE") return null;
  let channels = 0,
    rate = 0,
    bits = 0,
    format = 0,
    offset = 12,
    start = 0,
    length = 0;
  while (offset + 8 <= bytes.byteLength) {
    const name = tag(offset),
      size = view.getUint32(offset + 4, true),
      body = offset + 8;
    if (body + size > bytes.byteLength) return null;
    if (name === "fmt " && size >= 16) {
      format = view.getUint16(body, true);
      channels = view.getUint16(body + 2, true);
      rate = view.getUint32(body + 4, true);
      bits = view.getUint16(body + 14, true);
    }
    if (name === "data") {
      start = body;
      length = size;
    }
    offset = body + size + (size % 2);
  }
  if (
    format !== 1 ||
    bits !== 16 ||
    !channels ||
    channels > 2 ||
    !rate ||
    !length
  )
    return null;
  const frames = Math.floor(length / (channels * 2)),
    n = Math.min(count, frames),
    peaks: number[] = [];
  for (let b = 0; b < n; b++) {
    let peak = 0;
    for (
      let frame = Math.floor((b * frames) / n);
      frame < Math.floor(((b + 1) * frames) / n);
      frame++
    )
      for (let ch = 0; ch < channels; ch++)
        peak = Math.max(
          peak,
          Math.abs(
            view.getInt16(start + (frame * channels + ch) * 2, true) / 32768,
          ),
        );
    peaks.push(peak);
  }
  return { peaks, duration: frames / rate };
}
