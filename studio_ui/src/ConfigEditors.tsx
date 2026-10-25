import { useEffect, useState } from "react";
import type { Asset, StudioConfig } from "./types";
import { assetURL, shorten } from "./api";
import {
  Badge,
  Empty,
  Field,
  Icon,
  Notice,
  NumberField,
  Section,
  Toggle,
} from "./components";
type EditorProps = {
  config: StudioConfig;
  update: (recipe: (c: StudioConfig) => void) => void;
  canEdit: boolean;
};
export function BettingEditor({ config, update, canEdit }: EditorProps) {
  const [options, setOptions] = useState(config.bet.options.join(", "));
  const [counts, setCounts] = useState(config.bet.auto_counts.join(", "));
  useEffect(() => {
    setOptions(config.bet.options.join(", "));
    setCounts(config.bet.auto_counts.join(", "));
  }, [config.bet]);
  return (
    <div className="two-column">
      <Section
        eyebrow="VIRTUAL CREDITS"
        title="Betting policy"
        description="Denominasi disimpan sebagai decimal. Perubahan berlaku untuk ticket baru."
      >
        <div className="form-grid">
          <Field
            label="Pilihan bet"
            hint="Pisahkan dengan koma. Setiap nilai harus positif dan unik."
          >
            <input
              disabled={!canEdit}
              value={options}
              onChange={(e) => setOptions(e.target.value)}
              onBlur={() =>
                update((c) => {
                  c.bet.options = options
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean);
                })
              }
            />
          </Field>
          <Field label="Default bet">
            <select
              disabled={!canEdit}
              value={config.bet.default}
              onChange={(e) =>
                update((c) => {
                  c.bet.default = e.target.value;
                })
              }
            >
              {config.bet.options.map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </Field>
          <Field
            label="Saldo virtual awal"
            hint="Untuk session baru atau Reset Demo. Saldo session aktif tidak ditulis ulang."
          >
            <input
              disabled={!canEdit}
              inputMode="decimal"
              value={config.bet.initial_balance}
              onChange={(e) =>
                update((c) => {
                  c.bet.initial_balance = e.target.value;
                })
              }
            />
          </Field>
          <div className="summary-box">
            <span>Rentang yang ditawarkan</span>
            <strong>
              {config.bet.options[0] ?? "—"} <span>→</span>{" "}
              {config.bet.options.at(-1) ?? "—"}
            </strong>
            <small>
              {config.bet.options.length} denominasi · virtual credits
            </small>
          </div>
        </div>
      </Section>
      <Section
        eyebrow="PLAYBACK & AUTOMATION"
        title="Auto & Turbo"
        description="Auto menjalankan satu paid round pada satu waktu."
      >
        <Field
          label="Pilihan jumlah Auto"
          hint="Bilangan bulat, dipisahkan dengan koma."
        >
          <input
            disabled={!canEdit}
            value={counts}
            onChange={(e) => setCounts(e.target.value)}
            onBlur={() =>
              update((c) => {
                c.bet.auto_counts = counts
                  .split(",")
                  .map((x) => Number(x.trim()));
              })
            }
          />
        </Field>
        <Toggle
          disabled={!canEdit}
          label="Stop ketika masuk bonus"
          hint="Selesaikan paid round termasuk seluruh free spins terlebih dahulu."
          checked={config.bet.auto_stop_on_bonus}
          onChange={(v) =>
            update((c) => {
              c.bet.auto_stop_on_bonus = v;
            })
          }
        />
        <Field
          label="Stop Auto ketika payout mencapai × stake"
          hint="Kosong berarti tidak memakai batas kemenangan Auto."
        >
          <input
            type="number"
            min="0"
            step="any"
            disabled={!canEdit}
            value={config.bet.auto_stop_on_win_x ?? ""}
            onChange={(e) =>
              update((c) => {
                c.bet.auto_stop_on_win_x =
                  e.target.value === "" ? null : Number(e.target.value);
              })
            }
          />
        </Field>
        <NumberField
          label="Kecepatan animasi"
          disabled={!canEdit}
          value={config.presentation.animation_speed}
          min={0.5}
          max={2}
          step={0.05}
          hint="1 = standar. Kecepatan visual tidak memengaruhi hasil engine."
          onChange={(v) =>
            update((c) => {
              c.presentation.animation_speed = v;
            })
          }
        />
      </Section>
      <Section
        title="Presentasi kemenangan"
        description="Threshold visual terpisah dari nilai payout engine."
        className="span-two"
      >
        <div className="form-grid">
          <NumberField
            disabled={!canEdit}
            label="Big Win · × stake"
            value={config.presentation.big_win_x}
            min={1}
            onChange={(v) =>
              update((c) => {
                c.presentation.big_win_x = v;
              })
            }
          />
          <NumberField
            disabled={!canEdit}
            label="Mega Win · × stake"
            value={config.presentation.mega_win_x}
            min={1}
            onChange={(v) =>
              update((c) => {
                c.presentation.mega_win_x = v;
              })
            }
          />
        </div>
      </Section>
    </div>
  );
}
export function RulesEditor({ config, update, canEdit }: EditorProps) {
  const [advanced, setAdvanced] = useState(false),
    [json, setJson] = useState(""),
    [jsonError, setJsonError] = useState("");
  const m = config.math;
  const sum = Object.values(m.symbols).reduce((a, b) => a + b, 0);
  const setNumber = (key: keyof typeof m, value: number) =>
    update((c) => {
      c.math[key] = value;
    });
  return (
    <>
      <div className="inline-stats">
        <Badge tone="jade">Grid {m.grid.join(" / ")} · terkunci</Badge>
        <Badge>2.000 ways</Badge>
        <Badge tone={sum === 100 ? "jade" : "danger"}>
          Total bobot {sum} / 100
        </Badge>
        <Badge>Math {m.version}</Badge>
      </div>
      <Section
        eyebrow="GLOBAL GAME RULES"
        title="Rules & Paytable"
        description="Setiap simbol membayar pada 3, 4, atau 5 reel berurutan dari kiri. Gold adalah state tile."
        actions={
          <button
            className="button subtle"
            onClick={() => {
              setAdvanced(!advanced);
              setJson(JSON.stringify(m, null, 2));
            }}
          >
            JSON {advanced ? "tutup" : "advanced"}
          </button>
        }
      >
        <div className="table-scroll">
          <table className="paytable">
            <thead>
              <tr>
                <th>Simbol</th>
                <th>Bobot</th>
                <th>Draw</th>
                <th>3 reel</th>
                <th>4 reel</th>
                <th>5 reel</th>
                <th>Efektif base, 5 reel ×1</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(m.symbols).map(([symbol, weight]) => (
                <tr key={symbol}>
                  <td>
                    <span className="symbol-chip">{symbol}</span>
                  </td>
                  <td>
                    <input
                      aria-label={"Bobot " + symbol}
                      type="number"
                      min="1"
                      step="1"
                      disabled={!canEdit}
                      value={weight}
                      onChange={(e) =>
                        update((c) => {
                          c.math.symbols[symbol] = Number(e.target.value);
                        })
                      }
                    />
                  </td>
                  <td className="tabular muted">
                    {sum > 0 ? ((weight / sum) * 100).toFixed(1) : "—"}%
                  </td>
                  {[0, 1, 2].map((index) => (
                    <td key={index}>
                      <input
                        type="number"
                        step="any"
                        min="0"
                        disabled={!canEdit}
                        aria-label={
                          "Paytable " + symbol + " " + (index + 3) + " reel"
                        }
                        value={m.paytable[symbol]?.[index] ?? ""}
                        onChange={(e) =>
                          update((c) => {
                            c.math.paytable[symbol][index] = Number(
                              e.target.value,
                            );
                          })
                        }
                      />
                    </td>
                  ))}
                  <td className="tabular">
                    {(
                      Number(m.paytable[symbol]?.[2]) *
                      Number(m.paytable_scale_base)
                    ).toFixed(4)}
                    ×
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="footnote">
          Payout langkah = paytable × jumlah ways × multiplier × scale mode.
          Kredit = payout round × stake, dibatasi cap kumulatif.
        </p>
        {advanced && (
          <div className="advanced-editor">
            <Field label="Snapshot math JSON">
              <textarea
                rows={16}
                spellCheck={false}
                disabled={!canEdit}
                value={json}
                onChange={(e) => setJson(e.target.value)}
              />
            </Field>
            {jsonError && <Notice tone="danger">{jsonError}</Notice>}
            <button
              className="button"
              disabled={!canEdit}
              onClick={() => {
                try {
                  const parsed = JSON.parse(json);
                  if (
                    !parsed ||
                    typeof parsed !== "object" ||
                    Array.isArray(parsed)
                  )
                    throw Error("Snapshot harus berupa object.");
                  if (
                    !Array.isArray(parsed.grid) ||
                    !parsed.symbols ||
                    !parsed.paytable ||
                    !Array.isArray(parsed.base_multipliers) ||
                    !Array.isArray(parsed.bonus_multipliers) ||
                    Object.keys(parsed.symbols).some(
                      (key) =>
                        !Array.isArray(parsed.paytable[key]) ||
                        parsed.paytable[key].length !== 3,
                    )
                  )
                    throw Error(
                      "Snapshot harus memuat grid, symbols, 3 pay per simbol, dan kedua multiplier ladder.",
                    );
                  update((c) => {
                    c.math = parsed;
                  });
                  setJsonError("");
                  setAdvanced(false);
                } catch (e) {
                  setJsonError(e instanceof Error ? e.message : "JSON invalid");
                }
              }}
            >
              Terapkan ke draft lokal
            </button>
          </div>
        )}
      </Section>
      <div className="two-column">
        <Section
          title="Scatter & enhanced"
          description="Probabilitas per reel awal; bukan frekuensi bonus langsung."
        >
          <div className="form-grid">
            <NumberField
              disabled={!canEdit}
              label="Scatter per reel"
              min={0}
              max={0.25}
              value={m.scatter_probability_per_reel}
              onChange={(v) => setNumber("scatter_probability_per_reel", v)}
            />
            <NumberField
              disabled={!canEdit}
              label="Enhanced · reel 2–4"
              min={0}
              max={0.25}
              value={m.enhanced_probability_reels_2_to_4}
              onChange={(v) =>
                setNumber("enhanced_probability_reels_2_to_4", v)
              }
            />
            <NumberField
              disabled={!canEdit}
              label="Free spins untuk 3 scatter"
              min={0}
              step={1}
              value={m.free_spins_for_3_scatters}
              onChange={(v) => setNumber("free_spins_for_3_scatters", v)}
            />
            <NumberField
              disabled={!canEdit}
              label="Tambahan per scatter"
              min={0}
              step={1}
              value={m.extra_free_spins_per_additional_scatter}
              onChange={(v) =>
                setNumber("extra_free_spins_per_additional_scatter", v)
              }
            />
          </div>
          <Field label="Bonus: seluruh tile enhanced pada reel">
            <select
              disabled={!canEdit}
              value={m.bonus_all_enhanced_reel}
              onChange={(e) =>
                setNumber("bonus_all_enhanced_reel", Number(e.target.value))
              }
            >
              {[2, 3, 4].map((i) => (
                <option key={i} value={i}>
                  Reel {i}
                </option>
              ))}
            </select>
          </Field>
        </Section>
        <Section
          title="Multiplier & payout"
          description="Entry terakhir ladder berulang pada cascade berikutnya."
        >
          <div className="form-grid">
            {(["base_multipliers", "bonus_multipliers"] as const).map((key) => (
              <Field
                key={key}
                label={
                  key === "base_multipliers" ? "Base ladder" : "Bonus ladder"
                }
              >
                <input
                  disabled={!canEdit}
                  value={m[key].join(", ")}
                  onChange={(e) =>
                    update((c) => {
                      c.math[key] = e.target.value
                        .split(",")
                        .map((x) => Number(x.trim()));
                    })
                  }
                />
              </Field>
            ))}
            {(
              [
                "paytable_scale_base",
                "paytable_scale_bonus",
                "max_round_payout_x",
              ] as const
            ).map((key) => (
              <Field
                key={key}
                label={
                  key === "max_round_payout_x"
                    ? "Cap round · × paid stake"
                    : key === "paytable_scale_base"
                      ? "Scale base"
                      : "Scale bonus"
                }
              >
                <input
                  inputMode="decimal"
                  disabled={!canEdit}
                  value={m[key]}
                  onChange={(e) =>
                    update((c) => {
                      c.math[key] = e.target.value;
                    })
                  }
                />
              </Field>
            ))}
          </div>
          <Notice>
            Cap mencakup base + semua bonus dan retrigger. Perubahan math
            memerlukan hasil Math Lab yang cocok dengan hash draft.
          </Notice>
        </Section>
      </div>
    </>
  );
}
const names: Record<string, string> = {
  A: "Dot 2",
  B: "Dot 3",
  C: "Dot 4",
  D: "Dot 6",
  E: "Bamboo 2",
  F: "Bamboo 3",
  G: "Bamboo 4",
  H: "Bamboo 6",
  I: "一萬",
  J: "二萬",
  K: "五萬",
  L: "八萬",
  M: "中",
  N: "發",
  O: "白",
  W: "Wild",
  S: "Scatter",
};
export function TileEditor({
  config,
  update,
  canEdit,
  assets,
  onUpload,
  onRender,
}: {
  assets: Asset[];
  onUpload: (file: File, kind: string) => Promise<void>;
  onRender: (asset: Asset, recipe: Record<string, unknown>) => Promise<void>;
} & EditorProps) {
  const [symbol, setSymbol] = useState("A"),
    [variant, setVariant] = useState<"normal" | "gold">("normal"),
    [query, setQuery] = useState(""),
    [selectedAsset, setSelectedAsset] = useState(""),
    [fit, setFit] = useState("contain"),
    [mode, setMode] = useState("whole_tile"),
    [zoom, setZoom] = useState(1),
    [x, setX] = useState(0.5),
    [y, setY] = useState(0.5);
  const images = assets.filter(
    (a) => a.kind === "tile" && a.is_derivative && a.status === "ready",
  );
  const source = images.find((a) => a.id === selectedAsset),
    tile = config.tiles[symbol];
  const upload = async (file?: File) => {
    if (file) await onUpload(file, "tile");
  };
  return (
    <>
      <Section
        eyebrow="34 TILE SLOTS"
        title="Tile Studio"
        description="17 identitas × normal/gold. Artwork berubah tanpa mengubah simbol atau paytable."
        actions={
          <label className={"button " + (!canEdit ? "disabled" : "")}>
            <Icon name="upload" />
            Upload image
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              hidden
              disabled={!canEdit}
              onChange={(e) => {
                void upload(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
          </label>
        }
      >
        <div className="toolbar">
          <input
            aria-label="Cari simbol"
            className="search"
            placeholder="Cari simbol, nama, atau role…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="segmented">
            <button
              className={variant === "normal" ? "active" : ""}
              onClick={() => setVariant("normal")}
            >
              Normal
            </button>
            <button
              className={variant === "gold" ? "active" : ""}
              onClick={() => setVariant("gold")}
            >
              Gold
            </button>
          </div>
          <span className="muted small">218 × 327 · 2:3 RGBA</span>
        </div>
        <div className="tile-workspace">
          <div className="tile-grid">
            {Object.entries(config.tiles)
              .filter(([id]) =>
                (id + " " + names[id])
                  .toLowerCase()
                  .includes(query.toLowerCase()),
              )
              .map(([id, states]) => (
                <button
                  key={id}
                  className={"tile-card " + (id === symbol ? "selected" : "")}
                  onClick={() => setSymbol(id)}
                >
                  <div className="tile-thumb checker">
                    {assetURL(states[variant], assets) ? (
                      <img
                        src={assetURL(states[variant], assets)}
                        alt={names[id] + " " + variant}
                      />
                    ) : (
                      <span>Belum tersedia</span>
                    )}
                  </div>
                  <div>
                    <strong>{id}</strong>
                    <span>{names[id]}</span>
                  </div>
                </button>
              ))}
          </div>
          <aside className="inspector">
            <p className="eyebrow">SYMBOL {symbol}</p>
            <h3>
              {names[symbol]}{" "}
              <Badge tone="jade">
                {symbol === "W"
                  ? "Wild"
                  : symbol === "S"
                    ? "Scatter"
                    : "Ordinary"}
              </Badge>
            </h3>
            <div className="tile-pair">
              {(["normal", "gold"] as const).map((v) => (
                <div key={v}>
                  <div className="checker">
                    <img
                      src={assetURL(tile?.[v], assets)}
                      alt={symbol + " " + v}
                    />
                  </div>
                  <span>{v}</span>
                </div>
              ))}
            </div>
            <Field label={"Gambar untuk " + variant}>
              <select
                disabled={!canEdit}
                value={
                  images.some((a) => a.id === tile?.[variant])
                    ? tile?.[variant]
                    : ""
                }
                onChange={(e) => {
                  if (e.target.value)
                    update((c) => {
                      c.tiles[symbol][variant] = e.target.value;
                    });
                }}
              >
                <option value="">
                  {tile?.[variant]?.startsWith("/")
                    ? "Baseline bawaan"
                    : "Pilih derivative siap pakai"}
                </option>
                {images
                  .filter((a) => a.status === "ready")
                  .map((a) => (
                    <option value={a.id} key={a.id}>
                      {a.name}
                    </option>
                  ))}
              </select>
            </Field>
            <p className="hash">{tile?.[variant]}</p>
            <hr />
            <h4>Render dari original</h4>
            <Field label="Original image">
              <select
                disabled={!canEdit}
                value={selectedAsset}
                onChange={(e) => setSelectedAsset(e.target.value)}
              >
                <option value="">Pilih image dari library</option>
                {images
                  .filter((a) => a.status === "ready")
                  .map((a) => (
                    <option value={a.id} key={a.id}>
                      {a.name}
                    </option>
                  ))}
              </select>
            </Field>
            {source && (
              <>
                <div className="crop-preview checker">
                  <img
                    src={source.url}
                    style={{
                      objectFit: fit === "cover" ? "cover" : "contain",
                      objectPosition: `${x * 100}% ${y * 100}%`,
                      transform: `scale(${zoom})`,
                    }}
                    alt="Preview transform image"
                  />
                  <span className="crop-guide" />
                </div>
                <Field label="Mode artwork">
                  <select
                    disabled={!canEdit}
                    value={mode}
                    onChange={(e) => setMode(e.target.value)}
                  >
                    <option value="whole_tile">Seluruh tile</option>
                    <option value="glyph">Glyph + badan tile</option>
                  </select>
                </Field>
                <Field label="Fit">
                  <select
                    disabled={!canEdit}
                    value={fit}
                    onChange={(e) => setFit(e.target.value)}
                  >
                    <option value="contain">Contain · artwork utuh</option>
                    <option value="cover">Cover · isi frame</option>
                  </select>
                </Field>
                <NumberField
                  disabled={!canEdit}
                  label="Zoom"
                  value={zoom}
                  min={0.25}
                  max={4}
                  step={0.05}
                  onChange={setZoom}
                />
                <div className="form-grid">
                  <NumberField
                    disabled={!canEdit}
                    label="Anchor X"
                    value={x}
                    min={0}
                    max={1}
                    step={0.05}
                    onChange={setX}
                  />
                  <NumberField
                    disabled={!canEdit}
                    label="Anchor Y"
                    value={y}
                    min={0}
                    max={1}
                    step={0.05}
                    onChange={setY}
                  />
                </div>
                <button
                  className="button primary full"
                  disabled={!canEdit}
                  onClick={() =>
                    void onRender(source, {
                      mode,
                      fit,
                      zoom,
                      x,
                      y,
                      gold: variant === "gold",
                    })
                  }
                >
                  Render tile derivative
                </button>
                <small className="muted">
                  Preview crop membantu komposisi. Pilih derivative hasil render
                  untuk binding final.
                </small>
              </>
            )}
            <hr />
            <div className="asset-details">
              <span>Identitas engine</span>
              <strong>{symbol}</strong>
              <span>Source</span>
              <strong>{shorten(tile?.[variant], 18)}</strong>
              <span>Output</span>
              <strong>218 × 327</strong>
            </div>
          </aside>
        </div>
      </Section>
    </>
  );
}
export function SceneEditor({
  config,
  update,
  canEdit,
  assets,
  onUpload,
}: EditorProps & {
  assets: Asset[];
  onUpload: (file: File, kind: string) => Promise<void>;
}) {
  const images = assets.filter(
    (a) => a.kind === "scene" && a.is_derivative && a.status === "ready",
  );
  const labels: Record<string, string> = {
    background: "Root background",
    crown: "Crown & logo",
    board: "Board",
    footer: "Footer controls",
  };
  return (
    <>
      <div className="toolbar">
        <label className={"button " + (!canEdit ? "disabled" : "")}>
          <Icon name="upload" />
          Upload scene image
          <input
            hidden
            type="file"
            accept="image/png,image/jpeg,image/webp"
            disabled={!canEdit}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void onUpload(f, "scene");
              e.target.value = "";
            }}
          />
        </label>
        <span className="muted small">
          Full-image import · original tetap utuh
        </span>
      </div>
      <Notice>
        Slot kosong memakai artwork baseline. Bagian interaktif tetap dirender
        sebagai kontrol tersendiri agar gambar tidak menggandakan tombol atau
        teks.
      </Notice>
      <div className="two-column">
        {Object.entries(config.scene).map(([key, id]) => (
          <Section key={key} eyebrow="SCENE SLOT" title={labels[key] || key}>
            <div className={"scene-preview " + key}>
              {assetURL(id, assets) ? (
                <img src={assetURL(id, assets)} alt={labels[key] || key} />
              ) : (
                <Empty title="Baseline artwork" icon="scene">
                  Artwork bawaan tetap digunakan.
                </Empty>
              )}
            </div>
            <Field label="Image derivative">
              <select
                disabled={!canEdit}
                value={id ?? ""}
                onChange={(e) =>
                  update((c) => {
                    c.scene[key] = e.target.value || null;
                  })
                }
              >
                <option value="">Baseline artwork</option>
                {images.map((a) => (
                  <option value={a.id} key={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </Field>
            <p className="footnote">
              Preview pada halaman Preview & QA sebelum publish untuk memeriksa
              crop dan ruang kontrol.
            </p>
          </Section>
        ))}
      </div>
    </>
  );
}
